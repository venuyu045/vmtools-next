"""Map Art Build Task API routes.

Per implementation-plan.md Section 5 (API Design).
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from vmtools_next.api.deps import get_db, get_current_user, require_admin
from vmtools_next.data.models.build_map_art import (
    MapArtTask, MapArtMaterial, MapArtBotAssignment, MapArtBlockState, MapArtSupplyBox, MapArtSupplyTemplate,
    MapArtSupplyWarehouse, MapArtFoodBox, MapArtGlobalConfig,
)
from vmtools_next.adapters.litematica.litematica_parser import LitematicaParser
# 2026-10-28 架构重构：引擎唯一实现在 core.map_art（旧 map_art_coordinator /
# multi_bot_coordinator 已退化为 re-export shim）。API 只依赖这几个公共入口：
#   create_coordinator / register_coordinator / unregister_coordinator
#   resolve_coordinator（不分模式取活跃协调器）/ resolve_build_mode（build_mode 唯一默认值）
from vmtools_next.core.map_art import (
    create_coordinator,
    partition_rectangular,
    register_coordinator,
    resolve_build_mode,
    resolve_coordinator,
    unregister_coordinator,
)

logger = logging.getLogger("vmtools.map_art_api")
router = APIRouter(prefix="/api/build/map-art", tags=["map-art"])


# ──────────────────────────────────────────────
# build_mode 默认值 / 协调器定位（2026-10-28 重构后为单一来源）
# ──────────────────────────────────────────────
#
# B12（三处默认值不一致）与 P4（列式任务取不到协调器）在本文件的修法：
#
#   · build_mode 默认值 **不再在本文件定义** —— 唯一来源是
#     `core/map_art/registry.py: resolve_build_mode()`（默认 ``column``，
#     非法值/空值/NULL 一律回退 column）。模型列默认（data/models/build_map_art.py）、
#     API 创建、``execute_map_art_start`` 兜底、两个调度器全部走它；
#     历史显式存 ``strip`` 的任务仍按 strip 跑（兼容，不回改历史数据）。
#
#   · 协调器注册表也 **只剩一张**（`core/map_art/registry.py`）——旧版 strip 与
#     column 各一张表，本文件只查 strip 表 → 列式任务（默认模式）的
#     pause/resume/stop、bot 背包、日志、运行中增删 Bot 全部拿不到协调器。
#     现在统一 `resolve_coordinator(task_id)` / `unregister_coordinator(task_id)`。
#
# 本文件只保留两个「读协调器内存」的兼容小工具（新旧引擎字段名不同）。


def _coord_logs(coord, limit: int = 300) -> list[dict]:
    """读协调器内存活动日志（新旧引擎双兼容）。

    - 新引擎：``coord.activity`` 是 ``ActivityLog``（环形缓冲，``recent(limit)``）
    - 旧协调器（shim 前）：``coord._activity_log`` 是 deque
    """
    act = getattr(coord, "activity", None)
    if act is not None and hasattr(act, "recent"):
        try:
            return list(act.recent(limit))
        except Exception:
            pass
    legacy = getattr(coord, "_activity_log", None)
    if legacy is not None:
        try:
            return list(legacy)[-limit:]
        except Exception:
            pass
    return []


def _coord_placed_coords(coord) -> Optional[set]:
    """运行中已放置坐标集合（协调器级优先，其次聚合各 bot loop）。

    ``_placed_coords`` 在新引擎里挂在每个 ``BotRuntime``（``coord.loops[*]``）上，
    协调器本身没有 → 聚合后返回；全部为空则返回 None，让调用方回退读 DB
    （空集合 ≠ 没有放置，不能拿空集合短路 DB 查询）。
    """
    direct = getattr(coord, "_placed_coords", None)
    if direct is not None:
        return set(direct)
    loops = getattr(coord, "loops", None) or getattr(coord, "_loops", None)
    if not isinstance(loops, dict):
        return None
    merged: set = set()
    for loop in loops.values():
        coords = getattr(loop, "_placed_coords", None)
        if coords:
            merged |= set(coords)
    return merged or None


def _coord_total_blocks(coord) -> int:
    """协调器视角的任务总块数（新引擎 ``_total_blocks`` / 旧 ``total_blocks``）。"""
    for attr in ("total_blocks", "_total_blocks"):
        val = getattr(coord, attr, None)
        if isinstance(val, int) and val > 0:
            return val
    return 0


def _region_world(ba, task) -> dict:
    """bot 分配区域（DB 存投影相对坐标）→ 世界坐标。

    2026-10-28 B7 修复：``get_task`` 早已把 region 转世界坐标，但
    ``/tasks/{id}/blocks`` 两个分支仍原样返回相对坐标 → 同一份数据两套语义
    （前端按世界坐标渲染 blocks，区域框却按相对坐标画 → 整框偏移 origin）。
    全 API 统一：region 一律世界坐标。
    """
    ox = task.origin_x or 0
    oz = task.origin_z or 0
    return {
        "x_start": (ba.region_x_start or 0) + ox,
        "x_end": (ba.region_x_end or 0) + ox,
        "z_start": (ba.region_z_start or 0) + oz,
        "z_end": (ba.region_z_end or 0) + oz,
    }


# ──────────────────────────────────────────────
# 公共启动函数（2026-08-12，实施计划阶段 2）
# API 手动启动与任务调度器共用；调用方负责状态管理（置 running/pending/failed）
# ──────────────────────────────────────────────

async def execute_map_art_start(task_id: str, db: Session) -> tuple[bool, str]:
    """实际启动一个地图画任务（重建 layers → 建 coordinator → 收集 MF bots → start）。

    不检查/不修改 task.status（由调用方管理状态，调度器防竞态需要先置 running）。
    返回 (success, message)。
    """
    task = db.query(MapArtTask).filter(MapArtTask.task_id == task_id).first()
    if not task:
        return False, "任务不存在"

    # P2-7：投影解析结果在 create_task 时已写入 MapArtBlockState（DB 即解析缓存），
    # 启动时直接从 DB 重建 layers，避免对大投影重复 parse_file（512×512+ 耗时/IO）。
    # 2026-08-16 P0-5/B4：DB 统一存【世界坐标】（create 落库已转 origin+相对），
    # 此处重建回【相对坐标】供 coordinator（build_2d_matrix / _place_row 均用相对）。
    from vmtools_next.data.models.build_map_art import MapArtBlockState as _MABS
    _rows = db.query(_MABS).filter(_MABS.task_id == task_id).all()
    _layers: dict[int, list[tuple[int, int, int, str]]] = {}
    _ox, _oy, _oz = task.origin_x or 0, task.origin_y or 0, task.origin_z or 0
    for _r in _rows:
        _layers.setdefault(_r.y - _oy, []).append(
            (_r.x - _ox, _r.y - _oy, _r.z - _oz, _r.expected_block))
    if not _layers:
        return False, "任务无方块数据（投影解析结果缺失），无法启动"

    # 2026-08-19：按 build_mode 选择协调器（column=列式协作 / strip=旧分区独立）
    # 2026-10-28 B12 + 架构重构：build_mode 由 resolve_build_mode() 归一（唯一默认
    #   column），协调器由 `create_coordinator()` 统一工厂按模式创建——
    #   API 手动启动 / TaskScheduler 队列 / 定时任务三路共用本函数 → 完全同源。
    #   注册表也只剩一张（register_coordinator），不再区分 multi/strip。
    build_mode = resolve_build_mode(task)
    coord = create_coordinator(
        task_id=task_id,
        projection_data={
            "layers": _layers,
            "regions": {"Main": {
                "size": {"x": task.projection_size_x, "z": task.projection_size_z},
            }},
        },
        origin_x=task.origin_x,
        origin_y=task.origin_y,
        origin_z=task.origin_z,
        build_mode=build_mode,
    )
    # 地图画建造仅支持 mineflayer 引擎：所有 bot 必须为 MF，且只从 mineflayer pool 取 client
    from vmtools_next.main import get_pool_for_engine
    from vmtools_next.core.bot_engine import resolve_bot_engine
    bot_mcps = {}
    assignments = db.query(MapArtBotAssignment).filter(
        MapArtBotAssignment.task_id == task_id
    ).all()
    for ba in assignments:
        engine = resolve_bot_engine(ba.bot_id, db)
        if engine != "mineflayer":
            return False, f"地图画建造仅支持 Mineflayer Bot：{ba.bot_id} 的引擎为 {engine}"
        # 手动标记「工作中」的 bot 不派活（2026-08-13 任务管理）
        from vmtools_next.core.bot_work import ensure_available_for_work
        err = ensure_available_for_work(db, ba.bot_id, "地图画")
        if err:
            return False, err
        pool = get_pool_for_engine("mineflayer")
        client = pool.get_client(ba.bot_id) if pool else None
        if client:
            bot_mcps[ba.bot_id] = (ba.bot_name or ba.bot_id, client)

    if not bot_mcps:
        return False, "没有可用的 Mineflayer Bot（未连接）"

    try:
        await coord.start(bot_mcps)
        # 单注册表（column/strip 同一张，resolve_coordinator 不再需要 or 两次）
        register_coordinator(task_id, coord)
    except Exception as e:
        # 2026-08-14 审查修复：coord.start（连接 bot/初始化 loop）抛异常时
        # 会直接 500 且任务停留在 running（调用方已先置 running 落库）→
        # 捕获并返回失败，由调用方置 failed + 写 error_message。
        logger.exception("[%s] Map art start failed", task_id)
        return False, f"启动失败：{e}"
    return True, "started"


async def _broadcast_task_queue() -> None:
    """广播任务队列变化（任务中心实时刷新）。"""
    try:
        from vmtools_next.data.db import sio
        await sio.emit("task_queue_update", {"ts": datetime.now(timezone.utc).isoformat()})
    except Exception:
        pass


# ──────────────────────────────────────────────
# Pydantic schemas
# ──────────────────────────────────────────────

class MapArtTaskCreate(BaseModel):
    name: str
    projection_file_path: str
    origin_x: int = 0
    origin_y: int = 64
    origin_z: int = 0
    bot_ids: list[str] = []
    organization_id: Optional[str] = None
    # 投影朝向（2026-08-14）：绕 Y 轴顺时针旋转次数 0/1/2/3 = 0°/90°/180°/270°
    rotation: int = 0
    # 建造模式（2026-08-19）：column=新列式协作（默认）/ strip=旧分区独立
    build_mode: str = "column"


class MapArtTaskResponse(BaseModel):
    task_id: str
    name: str
    status: str
    projection_name: str
    projection_author: str
    projection_size_x: int
    projection_size_z: int
    total_blocks: int
    placed_blocks: int
    created_at: str
    # 投影朝向（2026-08-14）：0/1/2/3 = 0°/90°/180°/270°
    rotation: int = 0


class TaskControlRequest(BaseModel):
    action: str  # start | pause | resume | stop


# 控制动作中文标签（2026-08-13 汉化）
_ACTION_LABELS = {
    "start": "启动",
    "pause": "暂停",
    "resume": "继续",
    "stop": "停止",
}


class BotManageRequest(BaseModel):
    action: str  # add | remove
    bot_id: str


class SupplyConfigRequest(BaseModel):
    """补货传送指令（2026-08-14）：三个指令均可自定义 + 固定返回兜底指令。"""
    go: str = ""       # 前往补给点指令（如 "/ehomes mdssj"）
    save: str = ""     # 暂存当前位置指令（如 "/esethomes dth"）
    # 前端 JSON 字段名为 "return"（Python 关键字不能做字段名），用 alias 映射到 return_
    return_: str = Field(default="", alias="return")
    # 2026-08-14：固定返回指令（死亡/意外导致临时点不在地图画区域时的兜底传送）
    return_fixed: str = ""


class SupplyBoxCoord(BaseModel):
    x: int
    y: int
    z: int


class SupplyBoxItem(BaseModel):
    """一种材料对应的潜影盒坐标列表。"""
    item_id: str
    boxes: list[SupplyBoxCoord] = []


class SupplyBoxesRequest(BaseModel):
    items: list[SupplyBoxItem] = []


class FoodConfigRequest(BaseModel):
    """食物补货配置（2026-08-14 模块A）：猪排仓库 + 进食阈值。"""
    item_id: str = "minecraft:cooked_porkchop"
    go_command: str = "/res tp lixiangxiang.qwp"
    wait_after_go_ms: int = 5000
    eat_threshold_food: int = 15
    eat_threshold_health: int = 15


class SupplyTemplateCreate(BaseModel):
    """补货潜影盒模板（2026-08-14 二期）：可复用配置。"""
    name: str
    items: list[SupplyBoxItem] = []


class SupplyTemplateApply(BaseModel):
    task_id: str


class SleepPointRequest(BaseModel):
    """地图画建造睡觉点（2026-08-16）：床的方块坐标（世界坐标）。

    未配置（x/y/z 任意为 0）→ 清空睡觉点（建造循环跳过自动睡觉）。
    """
    x: int = 0
    y: int = 0
    z: int = 0


# 2026-10-28 B5：此处原有 `_load_global_warehouse(db)`（读 map_art_supply_warehouse
# 拼 {item_id: [(x,y,z)]}），全仓无任何调用点 —— 属死代码，已删除。
# 「全局仓库合并进任务补货配置」这件事在协调器内实现：
#   `MapArtCoordinator._load_supply_data()`（core/map_art_coordinator.py）自己查
#   `MapArtSupplyBox`（任务级）+ `MapArtSupplyWarehouse`（全局），任务级优先合并后
#   传给每个 BotBuildLoop；API 层不需要也不应该再算一遍。
# 全局仓库的读/写仍由本文件的 GET/PUT `/supply-warehouse` 两个端点负责。


def _default_supply_config() -> dict:
    """任务级补货指令默认值（config 可配，见 config.py map_art_supply_*_command）。"""
    from vmtools_next.config import get_config as _cfg
    try:
        mf = _cfg().mineflayer
        return {
            "go": getattr(mf, "map_art_supply_go_command", "/ehomes mdssj") or "/ehomes mdssj",
            "save": getattr(mf, "map_art_supply_save_command", "/esethomes dth") or "/esethomes dth",
            "return": getattr(mf, "map_art_supply_return_command", "/ehomes dth") or "/ehomes dth",
            "return_fixed": getattr(mf, "map_art_supply_fixed_return_command", "/ehomes mapart") or "/ehomes mapart",
        }
    except Exception:
        return {"go": "/ehomes mdssj", "save": "/esethomes dth", "return": "/ehomes dth",
                "return_fixed": "/ehomes mapart"}


def _parse_supply_config(raw: Optional[str]) -> dict:
    """解析任务级 supply_config（JSON），缺省回退默认。"""
    default = _default_supply_config()
    if not raw:
        return default
    try:
        data = json.loads(raw)
        if not isinstance(data, dict):
            return default
        return {
            "go": str(data.get("go") or default["go"]),
            "save": str(data.get("save") or default["save"]),
            "return": str(data.get("return") or default["return"]),
            "return_fixed": str(data.get("return_fixed") or default["return_fixed"]),
        }
    except Exception:
        return default


def _default_food_config() -> dict:
    """食物配置默认值（2026-08-14 模块A）。"""
    from vmtools_next.config import get_config as _cfg
    try:
        mf = _cfg().mineflayer
        return {
            "item_id": getattr(mf, "map_art_food_item", "minecraft:cooked_porkchop"),
            "go_command": getattr(mf, "map_art_food_go_command", "/res tp lixiangxiang.qwp"),
            "wait_after_go_ms": int(getattr(mf, "map_art_food_wait_after_go_ms", 5000)),
            "eat_threshold_food": int(getattr(mf, "map_art_eat_threshold_food", 15)),
            "eat_threshold_health": int(getattr(mf, "map_art_eat_threshold_health", 15)),
        }
    except Exception:
        return {
            "item_id": "minecraft:cooked_porkchop",
            "go_command": "/res tp lixiangxiang.qwp",
            "wait_after_go_ms": 5000,
            "eat_threshold_food": 15,
            "eat_threshold_health": 15,
        }


def _parse_food_config(raw: Optional[str]) -> dict:
    """解析任务级 food_config（JSON），缺省回退默认。"""
    default = _default_food_config()
    if not raw:
        return default
    try:
        data = json.loads(raw)
        if not isinstance(data, dict):
            return default
        return {
            "item_id": str(data.get("item_id") or default["item_id"]),
            "go_command": str(data.get("go_command") or default["go_command"]),
            "wait_after_go_ms": int(data.get("wait_after_go_ms") or default["wait_after_go_ms"]),
            "eat_threshold_food": int(data.get("eat_threshold_food") or default["eat_threshold_food"]),
            "eat_threshold_health": int(data.get("eat_threshold_health") or default["eat_threshold_health"]),
        }
    except Exception:
        return default


# ──────────────────────────────────────────────
# Routes
# ──────────────────────────────────────────────

@router.post("/tasks", response_model=MapArtTaskResponse)
async def create_task(
    data: MapArtTaskCreate,
    db: Session = Depends(get_db),
    user=Depends(require_admin),
):
    """Create a new map art build task from a Litematica projection file."""
    # 地图画建造仅支持 mineflayer 引擎（投影解析/建造执行均为 MF 专属）
    # 必须至少选 1 个 MF bot：空列表会创建 "unassigned" 分配 → 启动时被 MF-only
    # 校验拒绝 → 任务永远无法启动（P1 修复：创建时即强校验）。
    if not data.bot_ids:
        raise HTTPException(status_code=400, detail="请至少选择 1 个 Mineflayer Bot")
    from vmtools_next.core.bot_engine import resolve_bot_engine
    for bid in data.bot_ids:
        engine = resolve_bot_engine(bid, db)
        if engine != "mineflayer":
            raise HTTPException(
                status_code=400,
                detail=f"地图画建造仅支持 Mineflayer Bot：{bid} 的引擎为 {engine}",
            )
        # 手动标记「工作中」的 bot 不派活（2026-08-13 任务管理）
        from vmtools_next.core.bot_work import ensure_available_for_work
        err = ensure_available_for_work(db, bid, "地图画")
        if err:
            raise HTTPException(status_code=400, detail=err)

    # 路径安全：只允许解析已上传目录内的投影文件（防任意路径文件读取）
    from pathlib import Path as _Path
    _upload_dir = (_Path(__file__).resolve().parent.parent.parent.parent.parent
                   / "uploads" / "build_projections").resolve()
    _proj_path = _Path(data.projection_file_path).resolve()
    # 2026-08-14 审查修复：原用 str.startswith 前缀匹配，存在目录前缀边界绕过
    # （如 /uploads/build_projections_evil/x.litematic 可通过校验）→ 改用 is_relative_to
    try:
        _inside_upload = _proj_path.is_relative_to(_upload_dir)
    except Exception:
        _inside_upload = False
    if not _inside_upload or not _proj_path.is_file():
        raise HTTPException(status_code=400, detail="projection_file_path 必须位于上传目录内")
    # Parse projection to get metadata and materials
    try:
        parsed = await LitematicaParser.parse_file(data.projection_file_path)
        info = await LitematicaParser.get_projection_info(
            data.projection_file_path,
            origin_x=data.origin_x,
            origin_y=data.origin_y,
            origin_z=data.origin_z,
        )
        reqs = await LitematicaParser.get_material_requirements(data.projection_file_path)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"投影解析失败：{e}")
    # 2026-08-18：解析结果为空（投影无方块数据/解析失败静默返回空）→ 明确报错，
    # 避免创建 total_blocks=0 的空任务（前端预览/材料需求不显示的根因之一）。
    if (info.total_blocks or 0) <= 0 or not parsed.layers:
        raise HTTPException(
            status_code=400,
            detail="投影解析结果为空（0 个方块）：请检查投影文件是否包含方块数据，"
                   "或重新在 Litematica 中导出（确保有实际放置的方块）",
        )

    # P2-12：坐标系一致性校验——map_art 后端用「相对坐标+origin」放置、前端用投影
    # 坐标渲染，均假设投影 Position=(0,0,0)；带偏移投影会"什么都建不出"或坐标错位。
    for rname, rinfo in (parsed.regions or {}).items():
        pos = rinfo.get("position") or {}
        if pos.get("x") != 0 or pos.get("y") != 0 or pos.get("z") != 0:
            raise HTTPException(
                status_code=400,
                detail=(f"投影 region '{rname}' 原点偏移 "
                        f"({pos.get('x')},{pos.get('y')},{pos.get('z')})："
                        "请先在 Litematica 中把投影平移到原点 (0,0,0) 后重新导出"),
            )

    # 朝向旋转（2026-08-14）：解析结果统一按 rotation 旋转后落库，
    # 前端预览 / Bot 建造 / 断点续建全部使用旋转后坐标（DB 即旋转后的最终数据）。
    rotation = int(data.rotation or 0) % 4
    if rotation:
        from vmtools_next.adapters.litematica.litematica_parser import rotate_layers
        parsed.layers = rotate_layers(parsed.layers, rotation, info.size_x, info.size_z)
        # 90°/270° 时宽深互换（投影局部坐标已旋转，尺寸随之互换）
        if rotation in (1, 3):
            info.size_x, info.size_z = info.size_z, info.size_x

    # Create task
    task = MapArtTask(
        name=data.name,
        projection_file_path=data.projection_file_path,
        projection_name=info.name,
        projection_author=info.author,
        projection_size_x=info.size_x,
        projection_size_y=info.size_y,
        projection_size_z=info.size_z,
        projection_total_blocks=info.total_blocks,
        origin_x=data.origin_x,
        origin_y=data.origin_y,
        origin_z=data.origin_z,
        total_blocks=info.total_blocks,
        organization_id=data.organization_id or getattr(user, "organization_id", None),
        created_by=getattr(user, "game_id", str(user)),
        supply_config=json.dumps(_default_supply_config(), ensure_ascii=False),
        food_config=json.dumps(_default_food_config(), ensure_ascii=False),
        rotation=rotation,
        # 2026-08-19：新任务默认列式协作模式（多Bot排级蛇形）
        # 2026-10-28 B12：默认值与模型列默认 / getattr 兜底统一走 resolve_build_mode()
        # （= "column"）；传了非法值也回退 column，不再把脏值写进库。
        build_mode=resolve_build_mode(data.build_mode),
    )
    db.add(task)
    db.flush()

    # Material requirements（2026-08-14：display_name 存中文权威名，前端直接显示中文）
    from vmtools_next.core.item_names_zh import get_item_zh as _item_zh
    for req in reqs:
        mat = MapArtMaterial(
            task_id=task.task_id,
            item_id=req.item_id,
            display_name=_item_zh(req.item_id),
            required_count=req.count,
        )
        db.add(mat)

    # Initial bot assignments (regions)
    n_bots = max(len(data.bot_ids), 1)
    regions = partition_rectangular(info.size_x, info.size_z, n_bots)
    for i, bot_id in enumerate(data.bot_ids or ["unassigned"]):
        r = regions[i]
        ba = MapArtBotAssignment(
            task_id=task.task_id,
            bot_id=bot_id,
            region_x_start=r.x_start,
            region_x_end=r.x_end,
            region_z_start=r.z_start,
            region_z_end=r.z_end,
            blocks_total=r.block_count,
        )
        db.add(ba)

    # Block states（P2-19：bulk insert 分批提交，避免 16384+ 条单 commit 过慢）
    # ⚠️ 2026-08-13 修复：此前误写 `layers`（未定义变量）→ NameError 500；
    # 方块数据来自 parse_file 返回的 parsed.layers（y_offset → [(x,y,z,block)]，
    # 投影 Position=(0,0,0) 校验后为相对坐标 0..size-1）。
    # 2026-08-16 P0-5/B4：落库统一转【世界坐标】（origin + 相对），与运行中
    # _flush_db / _restore_progress / get_task_blocks 的世界坐标语义一致。
    _ox, _oy, _oz = data.origin_x or 0, data.origin_y or 0, data.origin_z or 0
    _payload = [
        {"task_id": task.task_id, "x": wx + _ox, "y": wy + _oy, "z": wz + _oz,
         "expected_block": block_id}
        for y_offset, blocks in parsed.layers.items()
        for wx, wy, wz, block_id in blocks
    ]
    for i in range(0, len(_payload), 1000):
        db.execute(MapArtBlockState.__table__.insert(), _payload[i:i + 1000])

    db.commit()

    return MapArtTaskResponse(
        task_id=task.task_id,
        name=task.name,
        status=task.status,
        projection_name=task.projection_name,
        projection_author=task.projection_author or "",
        projection_size_x=task.projection_size_x,
        projection_size_z=task.projection_size_z,
        total_blocks=task.total_blocks,
        placed_blocks=task.placed_blocks,
        created_at=task.created_at.isoformat() if task.created_at else "",
        rotation=task.rotation or 0,
    )


@router.get("/tasks")
def list_tasks(
    status: Optional[str] = None,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    """List map art build tasks, optionally filtered by status."""
    q = db.query(MapArtTask)
    if status:
        q = q.filter(MapArtTask.status == status)
    tasks = q.order_by(MapArtTask.created_at.desc()).limit(50).all()
    return {
        "tasks": [
            {
                "task_id": t.task_id,
                "name": t.name,
                "status": t.status,
                "projection_name": t.projection_name,
                "total_blocks": t.total_blocks,
                "placed_blocks": t.placed_blocks,
                "projection_size_x": t.projection_size_x,
                "projection_size_z": t.projection_size_z,
                "created_at": t.created_at.isoformat() if t.created_at else "",
            }
            for t in tasks
        ],
        "total": len(tasks),
    }


@router.get("/tasks/{task_id}")
def get_task(task_id: str, db: Session = Depends(get_db), user=Depends(require_admin)):
    """Get full task details including materials and bot assignments."""
    task = db.query(MapArtTask).filter(MapArtTask.task_id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")

    materials = db.query(MapArtMaterial).filter(
        MapArtMaterial.task_id == task_id
    ).all()
    bots = db.query(MapArtBotAssignment).filter(
        MapArtBotAssignment.task_id == task_id
    ).all()

    # 2026-08-16 审查修复：MapArtMaterial.placed_count 无更新路径 → 材料面板进度恒 0。
    # 以实际方块状态为准聚合：按 expected_block 分组统计 placed=True 的行数
    # （16384 行 × 一次 GROUP BY，索引友好；去 [ 后缀兼容组件数据）。
    from sqlalchemy import func as _func
    _placed_by_mat: dict[str, int] = {}
    try:
        _agg_rows = db.query(
            MapArtBlockState.expected_block, _func.count(),
        ).filter(
            MapArtBlockState.task_id == task_id,
            MapArtBlockState.placed.is_(True),
        ).group_by(MapArtBlockState.expected_block).all()
        for _eb, _cnt in _agg_rows:
            _key = str(_eb or "").split("[")[0]
            _placed_by_mat[_key] = _cnt
    except Exception:
        pass  # 聚合失败回退原 placed_count（保持接口可用）

    return {
        "task_id": task.task_id,
        "name": task.name,
        "description": task.description,
        "status": task.status,
        "error_message": task.error_message,
        "supply_config": _parse_supply_config(task.supply_config),
        "food_config": _parse_food_config(task.food_config),
        "sleep_point": {
            "x": task.sleep_x, "y": task.sleep_y, "z": task.sleep_z,
        } if (task.sleep_x is not None and task.sleep_y is not None and task.sleep_z is not None) else None,
        "rotation": task.rotation or 0,
        # 2026-08-19：建造模式（column=多Bot列式协作 / strip=旧分区独立）
        # 2026-10-28 B12：统一走 resolve_build_mode()（默认 column，不再 `or "strip"`）
        "build_mode": resolve_build_mode(task),
        "projection": {
            "file_path": task.projection_file_path,
            "name": task.projection_name,
            "author": task.projection_author,
            "size_x": task.projection_size_x,
            "size_y": task.projection_size_y,
            "size_z": task.projection_size_z,
            "total_blocks": task.projection_total_blocks,
        },
        "origin": {"x": task.origin_x, "y": task.origin_y, "z": task.origin_z},
        "progress": {
            "total_blocks": task.total_blocks,
            "placed_blocks": task.placed_blocks,
            "verified_blocks": task.verified_blocks,
        },
        "materials": [
            {
                "item_id": m.item_id,
                "display_name": m.display_name,
                "required": m.required_count,
                # 2026-08-16 审查修复：placed 以 block_states 聚合为准（原 placed_count 恒 0）
                "placed": _placed_by_mat.get((m.item_id or "").split("[")[0], m.placed_count or 0),
                "color_hex": m.color_hex,
            }
            for m in materials
        ],
        "bots": [
            {
                "bot_id": b.bot_id,
                "bot_name": b.bot_name,
                "state": b.state,
                # 2026-08-19：列式协作模式扩展（旧任务无该字段，前端回退 0/1）
                "column": b.column_index or 0,
                "squad_index": 1,
                # 2026-08-16 审查修复：region 为投影相对坐标，前端画布按世界坐标渲染
                # （blocks 已是世界坐标）——统一转世界坐标（origin + 相对），防区域框错位。
                "region": _region_world(b, task),
                # 权威字段（与 WS `build_bot_status` 一致）
                "blocks_placed": b.blocks_placed,
                "blocks_total": b.blocks_total,
                "current_row": b.current_row,
                "place_rate": b.place_rate,
                # ── 2026-10-28 A1 修复：后端补 `placed/total/rate` 别名 ──
                # 前端模板（MapArtBuildView.vue）读的是 bot.placed / bot.total / bot.rate，
                # 而本接口与 `build_bot_status` 给的是 blocks_placed/blocks_total/place_rate
                # → 每 bot 进度恒 0%、文本 `undefined / undefined`、速率恒 0.0。
                # 契约（重构方案 §四）：两组字段同时给，前端改不改都能显示。
                "placed": b.blocks_placed or 0,
                "total": b.blocks_total or 0,
                "rate": b.place_rate or 0.0,
            }
            for b in bots
        ],
        "created_at": task.created_at.isoformat() if task.created_at else "",
        "started_at": task.started_at.isoformat() if task.started_at else None,
        "completed_at": task.completed_at.isoformat() if task.completed_at else None,
    }


@router.post("/tasks/{task_id}/control")
async def control_task(
    task_id: str,
    data: TaskControlRequest,
    db: Session = Depends(get_db),
    user=Depends(require_admin),
):
    """Control a build task: start, pause, resume, stop."""
    task = db.query(MapArtTask).filter(MapArtTask.task_id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")

    # 2026-10-28 P4/A3：column/strip 双模式统一取协调器（列式任务此前取不到 → 暂停/停止静默失效）
    coordinator = resolve_coordinator(task_id)

    if data.action == "start":
        # 2026-08-14：支持从 failed /「未完成的 completed」/ cancelled 回退重启（断点续建）。
        # 允许状态：draft/pending（新建待启）+ failed（失败重试）
        #          + cancelled（手动停止后可重启）
        #          + completed 且 placed<total（被误判/中断的"完成"任务回退）
        startable = task.status in ("draft", "pending", "failed", "cancelled") or (
            task.status == "completed"
            and (task.placed_blocks or 0) < (task.total_blocks or 0)
        )
        if not startable:
            raise HTTPException(status_code=400, detail=f"任务当前状态（{task.status}）无法启动")
        # 终态重试前：清理残留 coordinator（防旧 progress 推送与新任务并存）
        if coordinator is not None:
            try:
                await coordinator.stop()
            except Exception:
                pass
            unregister_coordinator(task_id)
        # 清终态标记（保留 placed 进度——断点续建由 _verify_block 对世界状态兜底）
        if task.status in ("failed", "completed"):
            task.error_message = ""
            task.completed_at = None
        # 2026-08-12（实施计划阶段 2）：多任务并发由 TaskScheduler 统一调度——
        # 有 running 任务时不再 400 拒绝，而是置 pending 入队，当前任务完成后自动开始。
        running = db.query(MapArtTask).filter(
            MapArtTask.status == "running",
            MapArtTask.task_id != task_id,
        ).first()
        if running:
            task.status = "pending"
            db.commit()
            await _broadcast_task_queue()
            return {"task_id": task_id, "status": "pending",
                    "message": f"已有运行中的任务（{running.name}），已加入队列，完成后自动开始"}

        # 无 running：直接启动（先置 running 落库，防调度器/并发重复启动）
        task.status = "running"
        task.started_at = datetime.now(timezone.utc)
        db.commit()
        ok, msg = await execute_map_art_start(task_id, db)
        if not ok:
            task.status = "failed"
            task.error_message = msg
            db.commit()
            await _broadcast_task_queue()
            raise HTTPException(status_code=400, detail=msg)
        await _broadcast_task_queue()

    elif data.action == "pause":
        if coordinator:
            await coordinator.pause()
        task.status = "paused"
        db.commit()
        await _broadcast_task_queue()

    elif data.action == "resume":
        if coordinator:
            await coordinator.resume()
        task.status = "running"
        db.commit()
        await _broadcast_task_queue()

    elif data.action == "stop":
        if coordinator:
            await coordinator.stop()
            unregister_coordinator(task_id)
        task.status = "cancelled"
        task.completed_at = datetime.now(timezone.utc)
        db.commit()
        await _broadcast_task_queue()
        # 停止后立即尝试启动下一个排队任务（调度器联动）
        from vmtools_next.core.task_scheduler import get_task_scheduler
        _sched = get_task_scheduler()
        if _sched:
            await _sched.schedule_once()

    else:
        raise HTTPException(status_code=400, detail=f"未知操作：{data.action}")

    db.commit()
    return {"task_id": task_id, "status": task.status, "message": f"任务已{_ACTION_LABELS.get(data.action, data.action)}"}


@router.post("/tasks/{task_id}/bots/{bot_id}/sleep")
async def force_bot_sleep(task_id: str, bot_id: str,
                          db: Session = Depends(get_db),
                          user=Depends(require_admin)):
    """手动触发任务内指定 bot 睡觉（2026-08-18 前端「睡觉按钮」）。

    bot 在任务运行中 → coordinator.force_sleep（复用夜晚排队机制：暂停建造 →
    传床边 → 睡 → 天亮 → 传回 → 恢复）；bot 不在任务 → 走 mcc_bots 通用睡觉。
    """
    task = db.query(MapArtTask).filter(MapArtTask.task_id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    # 2026-10-28：双模式统一取协调器（列式任务此前取不到 → 睡觉按钮 409）
    coordinator = resolve_coordinator(task_id)
    if coordinator is None:
        raise HTTPException(status_code=409, detail="任务未在运行中（无 coordinator），请在 bot 管理页触发睡觉")
    try:
        result = await coordinator.force_sleep(bot_id)
        return {"task_id": task_id, "bot_id": bot_id, **result}
    except Exception as e:
        logger.warning("[%s] Force sleep %s error: %s", task_id, bot_id, e)
        raise HTTPException(status_code=500, detail=f"强制睡觉失败：{e}")


def _rebuild_assignments(task, db: Session) -> None:
    """未运行任务重新分配 bot 区域（2026-08-19 统一 add/remove 的 draft 分支）。

    - strip 模式：按 Z 轴重新分区（全 X 条带，region 字段更新）
    - column 模式：按顺序分配 column_index（1..n，启动时协调器统一用）
    仅更新非 released 的 assignment 记录。
    """
    try:
        survivors = db.query(MapArtBotAssignment).filter(
            MapArtBotAssignment.task_id == task.task_id,
            MapArtBotAssignment.state != "released",
        ).order_by(MapArtBotAssignment.id).all()
        if not survivors:
            return
        # 2026-10-28 B12：统一走 resolve_build_mode()（默认 column，不再 `or "strip"`）
        build_mode = resolve_build_mode(task)
        size_x = task.projection_size_x or 128
        size_z = task.projection_size_z or 128
        if build_mode == "column":
            # 列式：按顺序分配列号（列 x=1..n 为第1排），region 字段置整列虚拟范围
            for i, s in enumerate(survivors):
                col = i + 1
                s.column_index = col
                s.region_x_start = col
                s.region_x_end = col
                s.region_z_start = 1
                s.region_z_end = size_z
                s.blocks_total = size_z
                s.blocks_placed = 0
                s.current_row = -1
        else:
            regions = partition_rectangular(size_x, size_z, len(survivors))
            for i, s in enumerate(survivors):
                r = regions[i]
                s.region_x_start = r.x_start
                s.region_x_end = r.x_end
                s.region_z_start = r.z_start
                s.region_z_end = r.z_end
                s.blocks_total = r.block_count
                s.blocks_placed = 0
                s.current_row = -1
    except Exception as _e:
        logger.warning("[%s] Rebuild assignments failed: %s", task.task_id, _e)


@router.post("/tasks/{task_id}/bots")
async def manage_task_bot(
    task_id: str,
    data: BotManageRequest,
    db: Session = Depends(get_db),
    user=Depends(require_admin),
):
    """P2-27：动态 bot 分配——add/remove bot。

    - add：仅运行中任务（把 remove_bot 释放的未完成区域分配给新 bot）
    - remove：
      · draft/pending（无 coordinator）：直接删除该 bot 的 assignment 记录，
        并按剩余 bot 数**重新分区**（剩余区域自动重新划分，不产生空洞）——2026-08-14 二期
      · running：停止 bot 并释放其未完成区域，等待后续 add 接管
    - 至少保留 1 个 bot；completed/cancelled/failed 不允许操作
    """
    task = db.query(MapArtTask).filter(MapArtTask.task_id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    # 2026-08-19：仅 completed 终态禁止操作 bot（failed/cancelled 可重新开始续建，
    # 用户需能调整 bot 后再重启；未运行任务直接改 assignment，运行中走 coordinator）
    if task.status == "completed":
        raise HTTPException(status_code=400, detail="任务已完成，不允许操作 Bot")

    # 2026-10-28 P4：column/strip 双模式统一取协调器（列式任务此前恒为 None →
    # 运行中增删 Bot 一律走「未运行」分支，改了 assignment 却没通知引擎）
    coordinator = resolve_coordinator(task_id)
    from vmtools_next.core.bot_engine import resolve_bot_engine
    from vmtools_next.main import get_pool_for_engine

    if data.action == "add":
        engine = resolve_bot_engine(data.bot_id, db)
        if engine != "mineflayer":
            raise HTTPException(status_code=400,
                                detail=f"地图画建造仅支持 Mineflayer Bot：{data.bot_id} 的引擎为 {engine}")
        # 手动标记「工作中」的 bot 不派活（2026-08-13 任务管理）
        from vmtools_next.core.bot_work import ensure_available_for_work
        err = ensure_available_for_work(db, data.bot_id, "地图画")
        if err:
            raise HTTPException(status_code=400, detail=err)

        if coordinator:
            # ── 运行中增 Bot（2026-10-28 P4 修复：移除 400 拦截，直接调协调器）──
            # 历史：2026-10-20 曾用 `hasattr(coordinator, "add_bot")` 探测 + 400 拒绝，
            #   因为列式协调器（MultiBotCoordinator，新任务默认 build_mode="column"）
            #   当时确实没有 add_bot/remove_bot → 运行中增删 Bot 必然 500，只能硬拦。
            # 现在：引擎侧（重构方案 §四）为列式协调器实现同名方法，语义为
            #   「未建的列重新编排、已建的列不动」，签名与旧 strip 协调器一致：
            #     add_bot(bot_id, bot_name, agent) -> bool
            #     remove_bot(bot_id) -> bool
            #   因此 API 不再做模式判断（那是引擎的职责），直接调用即可。
            pool = get_pool_for_engine("mineflayer")
            client = pool.get_client(data.bot_id) if pool else None
            if not client:
                raise HTTPException(status_code=400, detail=f"Bot {data.bot_id} 未连接")

            result = await coordinator.add_bot(data.bot_id, data.bot_id, client)
            # 兼容两种返回契约（防引擎重构期/旧协调器混跑）：
            #   新契约 bool（True=已接管）/ 旧 strip 契约 Region|None（None=无待接管区域）
            if isinstance(result, bool):
                ok, region = result, None
            else:
                ok, region = result is not None, result
            if not ok:
                raise HTTPException(
                    status_code=400,
                    detail="无法加入该运行任务：无待接管区域（均已分配/完成），"
                           "或该 Bot 已在任务中",
                )

            # DB：新增/复用 assignment 记录（同 bot 可能有 released 历史行 → 复用，防重复行）
            ba = db.query(MapArtBotAssignment).filter(
                MapArtBotAssignment.task_id == task_id,
                MapArtBotAssignment.bot_id == data.bot_id,
            ).order_by(MapArtBotAssignment.id.desc()).first()
            if ba is None:
                ba = MapArtBotAssignment(
                    task_id=task_id,
                    bot_id=data.bot_id,
                    bot_name=data.bot_id,
                )
                db.add(ba)
            ba.state = "running"
            region_payload = None
            if region is not None:
                ba.region_x_start = getattr(region, "x_start", 0)
                ba.region_x_end = getattr(region, "x_end", 0)
                ba.region_z_start = getattr(region, "z_start", 0)
                ba.region_z_end = getattr(region, "z_end", 0)
                ba.blocks_total = getattr(region, "block_count", 0)
                ba.blocks_placed = 0
                ba.current_row = -1
                region_payload = {
                    "x_start": ba.region_x_start, "x_end": ba.region_x_end,
                    "z_start": ba.region_z_start, "z_end": ba.region_z_end,
                }
            db.commit()
            return {
                "task_id": task_id, "bot_id": data.bot_id, "action": "add",
                "region": region_payload,
                "message": "Bot 已加入运行中任务（列式模式：未建列重新编排，已建列不动）",
            }

        # ── 未运行（draft/pending）：直接写入 assignment（2026-08-19 放开限制）──
        # 任务未启动时随时可添加 bot；启动时协调器统一分配列/区域。
        existing = db.query(MapArtBotAssignment).filter(
            MapArtBotAssignment.task_id == task_id,
            MapArtBotAssignment.bot_id == data.bot_id,
            MapArtBotAssignment.state != "released",
        ).first()
        if existing:
            raise HTTPException(status_code=400, detail=f"Bot {data.bot_id} 已在此任务中")
        ba = MapArtBotAssignment(
            task_id=task_id,
            bot_id=data.bot_id,
            bot_name=data.bot_id,
            state="idle",
            blocks_total=0,
        )
        db.add(ba)
        db.flush()
        # 重新分配（strip=分区 / column=列号），保持分配连续不产生空洞
        _rebuild_assignments(task, db)
        db.commit()
        return {"task_id": task_id, "bot_id": data.bot_id,
                "action": "add", "region": None,
                "message": "Bot 已加入任务（启动时统一分配列/区域）"}

    if data.action == "remove":
        # 至少保留 1 个 bot
        remaining = db.query(MapArtBotAssignment).filter(
            MapArtBotAssignment.task_id == task_id,
            MapArtBotAssignment.state != "released",
        ).count()
        if remaining <= 1:
            raise HTTPException(status_code=400, detail="至少保留 1 个 Bot")

        if coordinator:
            # ── 运行中减 Bot（2026-10-28 P4 修复：移除 400 拦截，直接调协调器）──
            # 与上面 add 分支同因：列式协调器已由引擎侧实现同名 remove_bot，
            # 语义为「停该 bot + 其未建列交回编队（已建列不动）」，返回 bool。
            ok = await coordinator.remove_bot(data.bot_id)
            if not ok:
                raise HTTPException(status_code=400,
                                    detail=f"Bot {data.bot_id} 不在该运行任务中")
            ba = db.query(MapArtBotAssignment).filter(
                MapArtBotAssignment.task_id == task_id,
                MapArtBotAssignment.bot_id == data.bot_id,
            ).order_by(MapArtBotAssignment.id.desc()).first()
            if ba:
                ba.state = "released"
            db.commit()
            return {"task_id": task_id, "bot_id": data.bot_id, "action": "remove",
                    "message": "Bot 已移出运行中任务（未建列交回编队，已建列保留）"}

        # draft/pending：直接删除 assignment + 按剩余 bot 重新分配（2026-08-14 二期；
        # 2026-08-19 统一走 _rebuild_assignments 支持 column 列号重排）
        ba = db.query(MapArtBotAssignment).filter(
            MapArtBotAssignment.task_id == task_id,
            MapArtBotAssignment.bot_id == data.bot_id,
        ).first()
        if not ba:
            raise HTTPException(status_code=404, detail=f"Bot {data.bot_id} 不在任务中")
        db.delete(ba)
        db.flush()
        _rebuild_assignments(task, db)
        survivors = db.query(MapArtBotAssignment).filter(
            MapArtBotAssignment.task_id == task_id,
            MapArtBotAssignment.state != "released",
        ).count()
        db.commit()
        return {"task_id": task_id, "bot_id": data.bot_id, "action": "remove",
                "repartitioned": survivors}

    raise HTTPException(status_code=400, detail=f"未知操作：{data.action}")


@router.get("/tasks/{task_id}/supply-config")
def get_supply_config(task_id: str, db: Session = Depends(get_db), user=Depends(require_admin)):
    """读取任务级补货传送指令（三个指令均可自定义，缺省回退 config 默认）。"""
    task = db.query(MapArtTask).filter(MapArtTask.task_id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    return _parse_supply_config(task.supply_config)


@router.put("/tasks/{task_id}/supply-config")
def put_supply_config(task_id: str, data: SupplyConfigRequest, db: Session = Depends(get_db),
                      user=Depends(require_admin)):
    """保存任务级补货传送指令（go=前往补给点 / save=暂存位置 / return=返回工作位置）。"""
    task = db.query(MapArtTask).filter(MapArtTask.task_id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    # 2026-08-14 审查修复：空值回退 config 默认（_default_supply_config），
    # 此前硬编码 "/ehomes mdssj" 等，与 config.py 可配置项不一致
    _default = _default_supply_config()
    cfg = {
        "go": data.go.strip() or _default["go"],
        "save": data.save.strip() or _default["save"],
        "return": data.return_.strip() or _default["return"],
        # 2026-08-14：固定返回兜底指令（死亡/意外导致临时点不在地图画区域时用）
        "return_fixed": data.return_fixed.strip() or _default["return_fixed"],
    }
    task.supply_config = json.dumps(cfg, ensure_ascii=False)
    db.commit()
    return {"status": "ok", "supply_config": cfg}


@router.get("/tasks/{task_id}/supply-boxes")
def get_supply_boxes(task_id: str, db: Session = Depends(get_db), user=Depends(require_admin)):
    """读取任务全部材料的补货潜影盒坐标（按材料分组；含中文名）。"""
    task = db.query(MapArtTask).filter(MapArtTask.task_id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    rows = db.query(MapArtSupplyBox).filter(MapArtSupplyBox.task_id == task_id).order_by(
        MapArtSupplyBox.sort_order).all()
    materials = db.query(MapArtMaterial).filter(MapArtMaterial.task_id == task_id).all()
    from vmtools_next.core.item_names_zh import get_item_zh
    items = []
    for m in materials:
        boxes = [{"x": r.x, "y": r.y, "z": r.z} for r in rows if r.item_id == m.item_id]
        items.append({
            "item_id": m.item_id,
            # 中文名优先（权威映射），兼容旧任务英文 display_name
            "display_name": get_item_zh(m.item_id) or m.display_name or "",
            "boxes": boxes,
        })
    return {"items": items}


@router.put("/tasks/{task_id}/supply-boxes")
def put_supply_boxes(task_id: str, data: SupplyBoxesRequest, db: Session = Depends(get_db),
                     user=Depends(require_admin)):
    """批量保存任务补货潜影盒坐标（整体替换：先删旧再插新；1 材料可配多坐标）。"""
    task = db.query(MapArtTask).filter(MapArtTask.task_id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    # 整体替换
    db.query(MapArtSupplyBox).filter(MapArtSupplyBox.task_id == task_id).delete()
    for item in data.items:
        clean_item = item.item_id.split("[")[0]
        for i, box in enumerate(item.boxes):
            db.add(MapArtSupplyBox(
                task_id=task_id,
                item_id=clean_item,
                x=box.x, y=box.y, z=box.z,
                sort_order=i,
            ))
    db.commit()
    return {"status": "ok", "saved": sum(len(i.boxes) for i in data.items)}


@router.get("/supply-templates")
def list_supply_templates(db: Session = Depends(get_db), user=Depends(require_admin)):
    """补货潜影盒模板列表（2026-08-14 二期：可复用配置）。"""
    rows = db.query(MapArtSupplyTemplate).order_by(MapArtSupplyTemplate.id.desc()).all()
    result = []
    for t in rows:
        try:
            items = json.loads(t.items_json or "[]")
        except Exception:
            items = []
        result.append({
            "id": t.id,
            "name": t.name,
            "material_count": len(items),
            "items": items,
            "created_at": t.created_at.isoformat() if t.created_at else "",
        })
    return {"templates": result}


@router.post("/supply-templates")
def create_supply_template(data: SupplyTemplateCreate, db: Session = Depends(get_db),
                           user=Depends(require_admin)):
    """创建补货潜影盒模板（name + items）。"""
    name = data.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="模板名称不能为空")
    # 清洗 items（去空坐标、去前缀）
    items = []
    for it in data.items:
        boxes = [{"x": b.x, "y": b.y, "z": b.z} for b in it.boxes
                 if not (b.x == 0 and b.y == 0 and b.z == 0)]
        if boxes:
            items.append({"item_id": it.item_id.split("[")[0], "boxes": boxes})
    t = MapArtSupplyTemplate(name=name, items_json=json.dumps(items, ensure_ascii=False))
    db.add(t)
    db.commit()
    return {"status": "ok", "id": t.id}


@router.put("/supply-templates/{tpl_id}")
def update_supply_template(tpl_id: int, data: SupplyTemplateCreate, db: Session = Depends(get_db),
                           user=Depends(require_admin)):
    """更新补货潜影盒模板（改名/改坐标）。"""
    t = db.query(MapArtSupplyTemplate).filter(MapArtSupplyTemplate.id == tpl_id).first()
    if not t:
        raise HTTPException(status_code=404, detail="模板不存在")
    if data.name.strip():
        t.name = data.name.strip()
    items = []
    for it in data.items:
        boxes = [{"x": b.x, "y": b.y, "z": b.z} for b in it.boxes
                 if not (b.x == 0 and b.y == 0 and b.z == 0)]
        if boxes:
            items.append({"item_id": it.item_id.split("[")[0], "boxes": boxes})
    t.items_json = json.dumps(items, ensure_ascii=False)
    db.commit()
    return {"status": "ok", "id": t.id}


@router.delete("/supply-templates/{tpl_id}")
def delete_supply_template(tpl_id: int, db: Session = Depends(get_db), user=Depends(require_admin)):
    """删除补货潜影盒模板。"""
    t = db.query(MapArtSupplyTemplate).filter(MapArtSupplyTemplate.id == tpl_id).first()
    if not t:
        raise HTTPException(status_code=404, detail="模板不存在")
    db.delete(t)
    db.commit()
    return {"deleted": tpl_id}


@router.post("/supply-templates/{tpl_id}/apply")
def apply_supply_template(tpl_id: int, data: SupplyTemplateApply, db: Session = Depends(get_db),
                          user=Depends(require_admin)):
    """把模板应用到任务（2026-08-14 二期：按任务实际材料交集过滤，整体覆盖任务配置）。"""
    t = db.query(MapArtSupplyTemplate).filter(MapArtSupplyTemplate.id == tpl_id).first()
    if not t:
        raise HTTPException(status_code=404, detail="模板不存在")
    task = db.query(MapArtTask).filter(MapArtTask.task_id == data.task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")

    # 任务实际材料集合（交集过滤）
    task_materials = {m.item_id.split("[")[0] for m in db.query(MapArtMaterial).filter(
        MapArtMaterial.task_id == task.task_id).all()}
    try:
        tpl_items = json.loads(t.items_json or "[]")
    except Exception:
        tpl_items = []

    # 整体替换任务潜影盒配置
    db.query(MapArtSupplyBox).filter(MapArtSupplyBox.task_id == task.task_id).delete()
    saved = 0
    for it in tpl_items:
        item_id = (it.get("item_id") or "").split("[")[0]
        if not item_id or item_id not in task_materials:
            continue  # 只导入任务存在的材料
        for i, box in enumerate(it.get("boxes") or []):
            db.add(MapArtSupplyBox(
                task_id=task.task_id,
                item_id=item_id,
                x=int(box["x"]), y=int(box["y"]), z=int(box["z"]),
                sort_order=i,
            ))
            saved += 1
    db.commit()
    return {"status": "ok", "applied_materials": saved > 0, "saved": saved}


@router.get("/supply-warehouse")
def get_supply_warehouse(db: Session = Depends(get_db), user=Depends(require_admin)):
    """读取全局补货仓库（2026-08-14 三期）：全部材料 → 潜影盒坐标映射。"""
    rows = db.query(MapArtSupplyWarehouse).order_by(MapArtSupplyWarehouse.item_id).all()
    items = []
    for r in rows:
        try:
            boxes = json.loads(r.boxes_json or "[]")
        except Exception:
            boxes = []
        items.append({"item_id": r.item_id, "boxes": boxes})
    return {"items": items}


@router.put("/supply-warehouse")
def put_supply_warehouse(data: SupplyBoxesRequest, db: Session = Depends(get_db),
                         user=Depends(require_admin)):
    """整体保存全局补货仓库（2026-08-14 三期）：`[{item_id, boxes:[{x,y,z}]}]`。

    整体替换：先删旧再插新。任务补货时会自动合并全局仓库（任务级优先）。
    """
    # 清洗：去空坐标、去前缀、去空材料
    cleaned = []
    for it in data.items:
        item_id = it.item_id.split("[")[0]
        boxes = [{"x": b.x, "y": b.y, "z": b.z} for b in it.boxes
                 if not (b.x == 0 and b.y == 0 and b.z == 0)]
        if item_id and boxes:
            cleaned.append((item_id, boxes))
    # 整体替换
    db.query(MapArtSupplyWarehouse).delete()
    for item_id, boxes in cleaned:
        db.add(MapArtSupplyWarehouse(item_id=item_id, boxes_json=json.dumps(boxes, ensure_ascii=False)))
    db.commit()
    return {"status": "ok", "materials": len(cleaned)}


# ── 食物补货配置（2026-08-14 模块A；2026-08-18 全局同步）──────────────────

def _load_global_food_config(db: Session) -> dict:
    """读取【全局】食物配置（map_art_global_config 单行 id=1，含食物潜影盒坐标）。

    2026-08-18 用户需求：一个任务里改了，其他任务同步生效——食物配置
    （含食物潜影盒坐标 food_boxes）改为全局一份。首次无记录 → 默认值；
    兼容旧任务级 food_config / MapArtFoodBox 作为迁移源。
    """
    _default = _default_food_config()
    result = {
        **_default,
        "food_boxes": [],
    }
    row = db.query(MapArtGlobalConfig).filter(MapArtGlobalConfig.id == 1).first()
    if row and row.config_json:
        try:
            data = json.loads(row.config_json)
            if isinstance(data, dict):
                result = {
                    "item_id": str(data.get("item_id") or _default["item_id"]),
                    "go_command": str(data.get("go_command") or _default["go_command"]),
                    "wait_after_go_ms": int(data.get("wait_after_go_ms") or _default["wait_after_go_ms"]),
                    "eat_threshold_food": int(data.get("eat_threshold_food") or _default["eat_threshold_food"]),
                    "eat_threshold_health": int(data.get("eat_threshold_health") or _default["eat_threshold_health"]),
                    "food_boxes": [
                        {"x": int(b["x"]), "y": int(b["y"]), "z": int(b["z"])}
                        for b in (data.get("food_boxes") or []) if isinstance(b, dict) and "x" in b
                    ],
                }
                return result
        except Exception:
            pass
    # 2026-08-18：全局有记录但 food_boxes 为空时，从旧任务表 MapArtFoodBox 补齐
    # （防止旧任务已配坐标、全局因历史写入空列表而丢失）
    if row and row.config_json and not result.get("food_boxes"):
        try:
            legacy = db.query(MapArtFoodBox).order_by(MapArtFoodBox.sort_order).all()
            if legacy:
                result["food_boxes"] = [{"x": r.x, "y": r.y, "z": r.z} for r in legacy]
        except Exception:
            pass
    # 兼容迁移：旧任务级 food_config 有自定义 → 提升为全局（一次性）
    try:
        custom = db.query(MapArtTask.food_config).filter(
            MapArtTask.food_config.isnot(None),
            MapArtTask.food_config != "",
        ).first()
        if custom and custom[0]:
            cfg = _parse_food_config(custom[0])
            if cfg != _default:
                result.update(cfg)
    except Exception:
        pass
    # 兼容迁移：旧任务级 MapArtFoodBox 有坐标 → 提升为全局（一次性）
    try:
        legacy_boxes = db.query(MapArtFoodBox).filter(
            MapArtFoodBox.item_id == "minecraft:cooked_porkchop",
        ).order_by(MapArtFoodBox.sort_order).first()
        if legacy_boxes is not None:
            old_rows = db.query(MapArtFoodBox).order_by(MapArtFoodBox.sort_order).all()
            if old_rows:
                result["food_boxes"] = [{"x": r.x, "y": r.y, "z": r.z} for r in old_rows]
                _save_global_food_config(db, result)
    except Exception:
        pass
    return result


def _save_global_food_config(db: Session, cfg: dict) -> None:
    """写入【全局】食物配置（单行 id=1）。"""
    row = db.query(MapArtGlobalConfig).filter(MapArtGlobalConfig.id == 1).first()
    if row is None:
        row = MapArtGlobalConfig(id=1, config_json="{}")
        db.add(row)
    row.config_json = json.dumps(cfg, ensure_ascii=False)
    db.commit()


@router.get("/tasks/{task_id}/food-config")
def get_food_config(task_id: str, db: Session = Depends(get_db), user=Depends(require_admin)):
    """读取食物配置（2026-08-18 起为【全局共享】：所有任务同一份，一个任务改处处生效）。"""
    task = db.query(MapArtTask).filter(MapArtTask.task_id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    return _load_global_food_config(db)


@router.put("/tasks/{task_id}/food-config")
def put_food_config(task_id: str, data: FoodConfigRequest, db: Session = Depends(get_db),
                    user=Depends(require_admin)):
    """保存食物配置（2026-08-18 起为【全局共享】：写全局，所有任务同步）。"""
    task = db.query(MapArtTask).filter(MapArtTask.task_id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    _default = _default_food_config()
    _cur = _load_global_food_config(db)  # 保留现有 food_boxes
    cfg = {
        "item_id": (data.item_id or "").strip() or _default["item_id"],
        "go_command": (data.go_command or "").strip() or _default["go_command"],
        "wait_after_go_ms": data.wait_after_go_ms or _default["wait_after_go_ms"],
        "eat_threshold_food": data.eat_threshold_food or _default["eat_threshold_food"],
        "eat_threshold_health": data.eat_threshold_health or _default["eat_threshold_health"],
        "food_boxes": _cur.get("food_boxes") or [],
    }
    _save_global_food_config(db, cfg)
    return {"status": "ok", "food_config": cfg, "global": True}


@router.get("/tasks/{task_id}/food-boxes")
def get_food_boxes(task_id: str, db: Session = Depends(get_db), user=Depends(require_admin)):
    """读取食物潜影盒坐标（2026-08-18 起为【全局共享】：所有任务同一份）。

    ⚠️ 修复：此前漏改仍读任务表（put 写全局、get 读任务表 → 保存后读不到
    「无法保存」、A 任务配置 B 任务不显示「没同步」）。
    """
    task = db.query(MapArtTask).filter(MapArtTask.task_id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    cfg = _load_global_food_config(db)
    return {
        "item_id": cfg.get("item_id", "minecraft:cooked_porkchop"),
        "boxes": cfg.get("food_boxes") or [],
    }


@router.put("/tasks/{task_id}/food-boxes")
def put_food_boxes(task_id: str, data: SupplyBoxesRequest, db: Session = Depends(get_db),
                   user=Depends(require_admin)):
    """批量保存食物潜影盒坐标（2026-08-18 起为【全局共享】：写全局，所有任务同步）。"""
    task = db.query(MapArtTask).filter(MapArtTask.task_id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    cfg = _load_global_food_config(db)  # 保留现有食物配置
    boxes: list[dict] = []
    for item in data.items:
        for b in item.boxes:
            boxes.append({"x": int(b.x), "y": int(b.y), "z": int(b.z)})
    cfg["food_boxes"] = boxes
    _save_global_food_config(db, cfg)
    return {"status": "ok", "boxes": boxes, "global": True}


@router.get("/tasks/{task_id}/sleep-point")
def get_sleep_point(task_id: str, db: Session = Depends(get_db), user=Depends(require_admin)):
    """读取任务睡觉点（2026-08-16）：床的方块坐标；未配置返回 None。"""
    task = db.query(MapArtTask).filter(MapArtTask.task_id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    if task.sleep_x is None or task.sleep_y is None or task.sleep_z is None:
        return {"x": None, "y": None, "z": None}
    return {"x": task.sleep_x, "y": task.sleep_y, "z": task.sleep_z}


@router.put("/tasks/{task_id}/sleep-point")
def put_sleep_point(task_id: str, data: SleepPointRequest, db: Session = Depends(get_db),
                    user=Depends(require_admin)):
    """保存任务睡觉点（床的方块坐标，世界坐标）；全 0 → 清空（跳过自动睡觉）。"""
    task = db.query(MapArtTask).filter(MapArtTask.task_id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    if data.x == 0 and data.y == 0 and data.z == 0:
        task.sleep_x = task.sleep_y = task.sleep_z = None
    else:
        task.sleep_x, task.sleep_y, task.sleep_z = int(data.x), int(data.y), int(data.z)
    db.commit()
    return {"status": "ok",
            "sleep_point": {"x": task.sleep_x, "y": task.sleep_y, "z": task.sleep_z}}


@router.get("/tasks/{task_id}/logs")
def get_task_logs(task_id: str, db: Session = Depends(get_db), user=Depends(require_admin)):
    """读取任务活动日志（2026-08-14 终端 REST 轮询兜底）。

    前端 BuildLogPanel 除 socket 实时推送外，每 3s 轮询此接口增量拉取，
    避免 socket 事件丢失/缓存导致终端空白。
    """
    # 2026-10-28：单注册表取协调器（列式任务此前恒返回空日志）
    coord = resolve_coordinator(task_id)
    if not coord:
        return {"logs": []}
    return {"logs": _coord_logs(coord)}


@router.get("/tasks/{task_id}/bots/inventory")
async def get_task_bots_inventory(task_id: str, db: Session = Depends(get_db),
                                  user=Depends(require_admin)):
    """正在工作的 bot 的背包快照（2026-08-14：实时终端下方 bot 背包面板轮询）。"""
    # 2026-10-28：双模式统一取协调器（列式任务此前恒返回空背包）
    coord = resolve_coordinator(task_id)
    if not coord:
        return {"bots": []}
    return {"bots": await coord.get_bot_inventory()}


@router.get("/tasks/{task_id}/blocks/placed")
def get_task_placed_blocks(task_id: str, db: Session = Depends(get_db),
                           user=Depends(require_admin)):
    """P1-5：轻量增量接口——只返回已放置方块，供前端 2D 画布轮询刷新。

    相比全量 blocks（16384+ 条），placed 子集通常远小；前端每 5s 拉一次
    增量涂色，避免画布停留在页面加载快照。

    ⚠️ 2026-08-16：运行中【优先读 coordinator 内存 _placed_coords】（放置成功即
    记录，不依赖 DB 行尾 flush）→ 前端预览像素实时变深；任务结束（无 coordinator）
    回退读 DB。
    """
    # 2026-10-28：单注册表取协调器；新引擎把 _placed_coords 挂在各 bot loop 上，
    # 由 _coord_placed_coords() 聚合（拿不到则回退 DB，绝不返回空集合短路）。
    coord = resolve_coordinator(task_id)
    if coord is not None:
        coords = _coord_placed_coords(coord)
        if coords is not None:
            blocks = [
                {"x": c[0], "y": c[1], "z": c[2],
                 "block": "placed"}
                for c in coords
            ]
            return {
                "task_id": task_id,
                "blocks": blocks,
                "placed": len(blocks),
                "total": _coord_total_blocks(coord),
            }

    task = db.query(MapArtTask).filter(MapArtTask.task_id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")

    blocks = db.query(MapArtBlockState).filter(
        MapArtBlockState.task_id == task_id,
        MapArtBlockState.placed.is_(True),
    ).all()

    return {
        "task_id": task_id,
        "blocks": [
            {"x": b.x, "y": b.y, "z": b.z,
             "block": b.actual_block or b.expected_block}
            for b in blocks
        ],
        "placed": len(blocks),
        "total": task.total_blocks or 0,
    }


@router.delete("/tasks/{task_id}")
def delete_task(task_id: str, db: Session = Depends(get_db), user=Depends(require_admin)):
    """Delete a task (only draft/cancelled/completed)."""
    task = db.query(MapArtTask).filter(MapArtTask.task_id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    if task.status not in ("draft", "cancelled", "completed"):
        raise HTTPException(status_code=400, detail=f"任务当前状态（{task.status}）不允许删除")
    # 2026-10-28：双注册表都摘（列式任务此前删完仍留幽灵协调器）
    unregister_coordinator(task_id)
    # 2026-08-14 审查修复：MapArtSupplyBox 未挂在 MapArtTask 的 relationship 上
    # （无级联），且 SQLite 默认未启用 foreign_keys（ondelete=CASCADE 不生效）→
    # 手动删除任务级补货潜影盒配置，防孤儿数据残留。
    db.query(MapArtSupplyBox).filter(
        MapArtSupplyBox.task_id == task_id).delete(synchronize_session=False)
    # 2026-08-14 模块A：清理食物潜影盒配置（无级联，防孤儿数据）
    db.query(MapArtFoodBox).filter(
        MapArtFoodBox.task_id == task_id).delete(synchronize_session=False)
    db.delete(task)
    db.commit()
    return {"deleted": task_id}


@router.get("/tasks/{task_id}/blocks")
def get_task_blocks(task_id: str, db: Session = Depends(get_db), user=Depends(require_admin)):
    """Return all block states for a task (for 3D frontend initialization).

    ⚠️ 2026-08-18 大图优化：> 5 万块时返回【行内同色 run-length】（runs）而非逐格
    blocks——47 万块投影逐格 JSON ≈25MB 下载+解析卡死/占满带宽；runs 按行内
    连续同色合并（{z, x_start, x_end, block, placed}）数据量降 1~2 个数量级，
    前端直接按 run 绘制。小图（≤5 万）保持逐格 blocks 兼容旧逻辑。

    ── 坐标口径（2026-10-28 B7 修复）──
    本接口**一律返回世界坐标**，与 `GET /tasks/{id}` 声明一致：
      · `blocks[].x/y/z` / `runs[].z,x_start,x_end`：DB 自 2026-08-16 起统一存世界
        坐标（`data/db.py` PRAGMA user_version=1 迁移过历史相对坐标行）；
      · `bots[].region`：DB 存的是**投影相对坐标** → 此处 + origin 转世界坐标
        （此前两个分支原样返回相对坐标，与 get_task 的世界坐标区域框语义冲突）；
      · `origin` / `size` 仍照旧返回，供前端自行换算（相对 = 世界 - origin）。
    新增 `"coords": "world"` 显式标记，防调用方再猜。
    """
    task = db.query(MapArtTask).filter(MapArtTask.task_id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")

    total = task.total_blocks or 0
    # Get bot assignments for region outlines
    bots = db.query(MapArtBotAssignment).filter(
        MapArtBotAssignment.task_id == task_id
    ).all()

    if total > 50000:
        # ── 大图：原生 SQL 读 (x,z,expected,placed)，内存按行合并 runs ──
        from sqlalchemy import text as _sql
        rows = db.execute(_sql(
            "SELECT x, z, expected_block, placed FROM map_art_block_states "
            "WHERE task_id = :t ORDER BY z, x"
        ), {"t": task_id}).fetchall()
        runs: list[dict] = []
        cur: Optional[dict] = None
        for _x, _z, _exp, _placed in rows:
            _p = bool(_placed)
            if cur and cur["z"] == _z and cur["block"] == _exp \
                    and cur["placed"] == _p and _x == cur["x_end"] + 1:
                cur["x_end"] = _x
            else:
                cur = {"z": _z, "x_start": _x, "x_end": _x,
                       "block": _exp, "placed": _p}
                runs.append(cur)
        return {
            "task_id": task_id,
            "runs": runs,
            "is_runs": True,
            "coords": "world",
            "total": len(rows),
            "placed": task.placed_blocks or 0,
            # 2026-10-28 B7：region 转世界坐标（与 get_task 一致）
            "bots": [
                {"bot_id": ba.bot_id, "bot_name": ba.bot_name, "state": ba.state,
                 "region": _region_world(ba, task)}
                for ba in bots
            ],
            "origin": {"x": task.origin_x, "y": task.origin_y, "z": task.origin_z},
            "size": {"x": task.projection_size_x, "z": task.projection_size_z},
        }

    blocks = db.query(MapArtBlockState).filter(
        MapArtBlockState.task_id == task_id
    ).all()

    return {
        "task_id": task_id,
        "blocks": [
            {"x": b.x, "y": b.y, "z": b.z,
             "expected": b.expected_block, "actual": b.actual_block,
             "placed": b.placed, "verified": b.verified}
            for b in blocks
        ],
        "coords": "world",
        # 2026-10-28 B7：region 转世界坐标（与 get_task 一致）
        "bots": [
            {"bot_id": ba.bot_id, "bot_name": ba.bot_name, "state": ba.state,
             "region": _region_world(ba, task)}
            for ba in bots
        ],
        "origin": {"x": task.origin_x, "y": task.origin_y, "z": task.origin_z},
        "size": {"x": task.projection_size_x, "z": task.projection_size_z},
        "total": len(blocks),
        "placed": task.placed_blocks or 0,
    }


# ──────────────────────────────────────────────
# Projection upload
# ──────────────────────────────────────────────

@router.post("/projections/upload")
async def upload_projection(
    file: UploadFile = File(...),
    user=Depends(require_admin),
):
    """Upload a .litematic file and return its metadata + material requirements.

    File is saved to a configured upload directory.
    """
    from pathlib import Path, PurePosixPath

    if not file.filename or not file.filename.endswith(".litematic"):
        raise HTTPException(400, "仅支持 .litematic 投影文件")
    content = await file.read()
    if len(content) > 50 * 1024 * 1024:
        raise HTTPException(400, "文件过大（上限 50MB）")

    # Save to uploads directory (absolute path)；文件名只取 basename，杜绝 ../ 穿越
    BASE = Path(__file__).resolve().parent.parent.parent.parent.parent  # backend/
    upload_dir = BASE / "uploads" / "build_projections"
    upload_dir.mkdir(parents=True, exist_ok=True)
    safe_name = PurePosixPath(file.filename.replace("\\", "/")).name
    file_path = upload_dir / safe_name
    with open(file_path, "wb") as f:
        f.write(content)

    # Return absolute path
    abs_path = str(file_path.resolve())

    # Parse and return metadata
    parsed = await LitematicaParser.parse_file(abs_path)
    info = await LitematicaParser.get_projection_info(abs_path)
    reqs = await LitematicaParser.get_material_requirements(abs_path)

    return {
        "file_path": abs_path,
        "projection_info": {
            "name": info.name,
            "author": info.author,
            "total_blocks": info.total_blocks,
            "size": {"x": info.size_x, "y": info.size_y, "z": info.size_z},
        },
        "material_requirements": [
            {
                "item_id": r.item_id,
                "display_name": r.display_name,
                "count": r.count,
            }
            for r in reqs
        ],
    }
