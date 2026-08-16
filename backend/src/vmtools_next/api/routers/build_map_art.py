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
    MapArtSupplyWarehouse, MapArtFoodBox,
)
from vmtools_next.adapters.litematica.litematica_parser import LitematicaParser
from vmtools_next.core.map_art_coordinator import (
    MapArtCoordinator,
    partition_rectangular,
    get_coordinator,
    register_coordinator,
    unregister_coordinator,
)

logger = logging.getLogger("vmtools.map_art_api")
router = APIRouter(prefix="/api/build/map-art", tags=["map-art"])


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

    coord = MapArtCoordinator(
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


def _load_global_warehouse(db: Session) -> dict[str, list[tuple[int, int, int]]]:
    """读取全局补货仓库（材料 → 潜影盒坐标列表）。"""
    result: dict[str, list[tuple[int, int, int]]] = {}
    rows = db.query(MapArtSupplyWarehouse).all()
    for r in rows:
        try:
            boxes = json.loads(r.boxes_json or "[]")
            result[r.item_id] = [(int(b["x"]), int(b["y"]), int(b["z"])) for b in boxes if "x" in b]
        except Exception:
            continue
    return result


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
        "rotation": task.rotation or 0,
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
                # 2026-08-16 审查修复：region 为投影相对坐标，前端画布按世界坐标渲染
                # （blocks 已是世界坐标）——统一转世界坐标（origin + 相对），防区域框错位。
                "region": {
                    "x_start": (b.region_x_start or 0) + (task.origin_x or 0),
                    "x_end": (b.region_x_end or 0) + (task.origin_x or 0),
                    "z_start": (b.region_z_start or 0) + (task.origin_z or 0),
                    "z_end": (b.region_z_end or 0) + (task.origin_z or 0),
                },
                "blocks_placed": b.blocks_placed,
                "blocks_total": b.blocks_total,
                "current_row": b.current_row,
                "place_rate": b.place_rate,
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

    coordinator = get_coordinator(task_id)

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
    if task.status in ("completed", "cancelled", "failed"):
        raise HTTPException(status_code=400, detail=f"任务当前状态（{task.status}）不允许操作 Bot")

    coordinator = get_coordinator(task_id)
    from vmtools_next.core.bot_engine import resolve_bot_engine
    from vmtools_next.main import get_pool_for_engine

    if data.action == "add":
        if not coordinator:
            raise HTTPException(status_code=400, detail="任务未在运行，仅运行中的任务可添加 Bot")
        engine = resolve_bot_engine(data.bot_id, db)
        if engine != "mineflayer":
            raise HTTPException(status_code=400,
                                detail=f"地图画建造仅支持 Mineflayer Bot：{data.bot_id} 的引擎为 {engine}")
        # 手动标记「工作中」的 bot 不派活（2026-08-13 任务管理）
        from vmtools_next.core.bot_work import ensure_available_for_work
        err = ensure_available_for_work(db, data.bot_id, "地图画")
        if err:
            raise HTTPException(status_code=400, detail=err)
        pool = get_pool_for_engine("mineflayer")
        client = pool.get_client(data.bot_id) if pool else None
        if not client:
            raise HTTPException(status_code=400, detail=f"Bot {data.bot_id} 未连接")

        region = await coordinator.add_bot(data.bot_id, data.bot_id, client)
        if region is None:
            raise HTTPException(status_code=400,
                                detail="无待接管区域（所有区域均已分配或完成）")
        # DB：新增 assignment 记录
        ba = MapArtBotAssignment(
            task_id=task_id,
            bot_id=data.bot_id,
            bot_name=data.bot_id,
            region_x_start=region.x_start,
            region_x_end=region.x_end,
            region_z_start=region.z_start,
            region_z_end=region.z_end,
            blocks_total=region.block_count,
            state="running",
        )
        db.add(ba)
        db.commit()
        return {"task_id": task_id, "bot_id": data.bot_id,
                "action": "add", "region": {
                    "x_start": region.x_start, "x_end": region.x_end,
                    "z_start": region.z_start, "z_end": region.z_end,
                }}

    if data.action == "remove":
        # 至少保留 1 个 bot
        remaining = db.query(MapArtBotAssignment).filter(
            MapArtBotAssignment.task_id == task_id,
            MapArtBotAssignment.state != "released",
        ).count()
        if remaining <= 1:
            raise HTTPException(status_code=400, detail="至少保留 1 个 Bot")

        if coordinator:
            # 运行中：停止 bot 并释放区域
            ok = await coordinator.remove_bot(data.bot_id)
            if not ok:
                raise HTTPException(status_code=400,
                                    detail=f"Bot {data.bot_id} 不在该运行任务中")
            ba = db.query(MapArtBotAssignment).filter(
                MapArtBotAssignment.task_id == task_id,
                MapArtBotAssignment.bot_id == data.bot_id,
            ).first()
            if ba:
                ba.state = "released"
            db.commit()
            return {"task_id": task_id, "bot_id": data.bot_id, "action": "remove"}

        # draft/pending：直接删除 assignment + 按剩余 bot 重新分区（2026-08-14 二期）
        ba = db.query(MapArtBotAssignment).filter(
            MapArtBotAssignment.task_id == task_id,
            MapArtBotAssignment.bot_id == data.bot_id,
        ).first()
        if not ba:
            raise HTTPException(status_code=404, detail=f"Bot {data.bot_id} 不在任务中")
        db.delete(ba)

        # 按剩余 bot 重新划分区域（全 X 条带，按 Z 切分）
        survivors = db.query(MapArtBotAssignment).filter(
            MapArtBotAssignment.task_id == task_id,
            MapArtBotAssignment.bot_id != data.bot_id,
        ).order_by(MapArtBotAssignment.id).all()
        if survivors:
            size_x = task.projection_size_x or 128
            size_z = task.projection_size_z or 128
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
        db.commit()
        return {"task_id": task_id, "bot_id": data.bot_id, "action": "remove",
                "repartitioned": len(survivors)}

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


# ── 食物补货配置（2026-08-14 模块A）─────────────────────────────────────

@router.get("/tasks/{task_id}/food-config")
def get_food_config(task_id: str, db: Session = Depends(get_db), user=Depends(require_admin)):
    """读取任务级食物配置（猪排仓库指令 + 进食阈值）。"""
    task = db.query(MapArtTask).filter(MapArtTask.task_id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    return _parse_food_config(task.food_config)


@router.put("/tasks/{task_id}/food-config")
def put_food_config(task_id: str, data: FoodConfigRequest, db: Session = Depends(get_db),
                    user=Depends(require_admin)):
    """保存任务级食物配置（item_id / go_command / 进食阈值均可自定义）。"""
    task = db.query(MapArtTask).filter(MapArtTask.task_id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    _default = _default_food_config()
    cfg = {
        "item_id": (data.item_id or "").strip() or _default["item_id"],
        "go_command": (data.go_command or "").strip() or _default["go_command"],
        "wait_after_go_ms": data.wait_after_go_ms or _default["wait_after_go_ms"],
        "eat_threshold_food": data.eat_threshold_food or _default["eat_threshold_food"],
        "eat_threshold_health": data.eat_threshold_health or _default["eat_threshold_health"],
    }
    task.food_config = json.dumps(cfg, ensure_ascii=False)
    db.commit()
    return {"status": "ok", "food_config": cfg}


@router.get("/tasks/{task_id}/food-boxes")
def get_food_boxes(task_id: str, db: Session = Depends(get_db), user=Depends(require_admin)):
    """读取任务食物潜影盒坐标（猪排仓库）。"""
    task = db.query(MapArtTask).filter(MapArtTask.task_id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    rows = db.query(MapArtFoodBox).filter(
        MapArtFoodBox.task_id == task_id
    ).order_by(MapArtFoodBox.sort_order).all()
    return {
        "item_id": "minecraft:cooked_porkchop",
        "boxes": [{"x": r.x, "y": r.y, "z": r.z} for r in rows],
    }


@router.put("/tasks/{task_id}/food-boxes")
def put_food_boxes(task_id: str, data: SupplyBoxesRequest, db: Session = Depends(get_db),
                   user=Depends(require_admin)):
    """批量保存任务食物潜影盒坐标（整体替换：先删旧再插新）。"""
    task = db.query(MapArtTask).filter(MapArtTask.task_id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    db.query(MapArtFoodBox).filter(MapArtFoodBox.task_id == task_id).delete()
    saved = 0
    for item in data.items:
        for i, box in enumerate(item.boxes):
            db.add(MapArtFoodBox(
                task_id=task_id,
                item_id=item.item_id.split("[")[0],
                x=box.x, y=box.y, z=box.z,
                sort_order=i,
            ))
            saved += 1
    db.commit()
    return {"status": "ok", "saved": saved}


@router.get("/tasks/{task_id}/logs")
def get_task_logs(task_id: str, db: Session = Depends(get_db), user=Depends(require_admin)):
    """读取任务活动日志（2026-08-14 终端 REST 轮询兜底）。

    前端 BuildLogPanel 除 socket 实时推送外，每 3s 轮询此接口增量拉取，
    避免 socket 事件丢失/缓存导致终端空白。
    """
    from vmtools_next.core.map_art_coordinator import get_coordinator
    coord = get_coordinator(task_id)
    if not coord:
        return {"logs": []}
    return {"logs": list(coord._activity_log)}


@router.get("/tasks/{task_id}/bots/inventory")
async def get_task_bots_inventory(task_id: str, db: Session = Depends(get_db),
                                  user=Depends(require_admin)):
    """正在工作的 bot 的背包快照（2026-08-14：实时终端下方 bot 背包面板轮询）。"""
    from vmtools_next.core.map_art_coordinator import get_coordinator
    coord = get_coordinator(task_id)
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
    from vmtools_next.core.map_art_coordinator import get_coordinator
    coord = get_coordinator(task_id)
    if coord is not None:
        coords = getattr(coord, "_placed_coords", None)
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
                "total": coord.total_blocks if hasattr(coord, "total_blocks") else 0,
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

    Returns full block list so the Three.js canvas can render immediately.
    """
    task = db.query(MapArtTask).filter(MapArtTask.task_id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")

    blocks = db.query(MapArtBlockState).filter(
        MapArtBlockState.task_id == task_id
    ).all()

    # Get bot assignments for region outlines
    bots = db.query(MapArtBotAssignment).filter(
        MapArtBotAssignment.task_id == task_id
    ).all()

    return {
        "task_id": task_id,
        "blocks": [
            {"x": b.x, "y": b.y, "z": b.z,
             "expected": b.expected_block, "actual": b.actual_block,
             "placed": b.placed, "verified": b.verified}
            for b in blocks
        ],
        "bots": [
            {"bot_id": ba.bot_id, "bot_name": ba.bot_name, "state": ba.state,
             "region": {"x_start": ba.region_x_start, "x_end": ba.region_x_end,
                        "z_start": ba.region_z_start, "z_end": ba.region_z_end}}
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
