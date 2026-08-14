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
from pydantic import BaseModel
from sqlalchemy.orm import Session

from vmtools_next.api.deps import get_db, get_current_user, require_admin
from vmtools_next.data.models.build_map_art import (
    MapArtTask, MapArtMaterial, MapArtBotAssignment, MapArtBlockState, MapArtSupplyBox,
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
    from vmtools_next.data.models.build_map_art import MapArtBlockState as _MABS
    _rows = db.query(_MABS).filter(_MABS.task_id == task_id).all()
    _layers: dict[int, list[tuple[int, int, int, str]]] = {}
    for _r in _rows:
        _layers.setdefault(_r.y, []).append((_r.x, _r.y, _r.z, _r.expected_block))
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

    await coord.start(bot_mcps)
    register_coordinator(task_id, coord)
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
    """补货传送指令（2026-08-14）：三个指令均可自定义。"""
    go: str = ""       # 前往补给点指令（如 "/ehomes mdssj"）
    save: str = ""     # 暂存当前位置指令（如 "/esethomes dth"）
    return_: str = ""  # 返回工作位置指令（如 "/ehomes dth"）——pydantic 字段名避开关键字


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


def _default_supply_config() -> dict:
    """任务级补货指令默认值（config 可配，见 config.py map_art_supply_*_command）。"""
    from vmtools_next.config import get_config as _cfg
    try:
        mf = _cfg().mineflayer
        return {
            "go": getattr(mf, "map_art_supply_go_command", "/ehomes mdssj") or "/ehomes mdssj",
            "save": getattr(mf, "map_art_supply_save_command", "/esethomes dth") or "/esethomes dth",
            "return": getattr(mf, "map_art_supply_return_command", "/ehomes dth") or "/ehomes dth",
        }
    except Exception:
        return {"go": "/ehomes mdssj", "save": "/esethomes dth", "return": "/ehomes dth"}


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
    if not str(_proj_path).startswith(str(_upload_dir)) or not _proj_path.is_file():
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
    # 方块数据来自 parse_file 返回的 parsed.layers（y_offset → [(x,y,z,block)]）
    _payload = [
        {"task_id": task.task_id, "x": wx, "y": wy, "z": wz,
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

    return {
        "task_id": task.task_id,
        "name": task.name,
        "description": task.description,
        "status": task.status,
        "error_message": task.error_message,
        "supply_config": _parse_supply_config(task.supply_config),
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
                "placed": m.placed_count,
                "color_hex": m.color_hex,
            }
            for m in materials
        ],
        "bots": [
            {
                "bot_id": b.bot_id,
                "bot_name": b.bot_name,
                "state": b.state,
                "region": {
                    "x_start": b.region_x_start, "x_end": b.region_x_end,
                    "z_start": b.region_z_start, "z_end": b.region_z_end,
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
        if task.status not in ("draft", "pending"):
            raise HTTPException(status_code=400, detail=f"任务当前状态（{task.status}）无法启动")
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
    """P2-27：动态 bot 分配——运行中任务 add/remove bot（区域接管）。

    - add：把 remove_bot 释放的未完成区域分配给新 bot（从 MF pool 取 client）
    - remove：停止 bot 并释放其未完成区域，等待后续 add 接管
    """
    task = db.query(MapArtTask).filter(MapArtTask.task_id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")

    coordinator = get_coordinator(task_id)
    if not coordinator:
        raise HTTPException(status_code=400, detail="任务未在运行，动态分配仅对运行中的任务生效")

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
        ok = await coordinator.remove_bot(data.bot_id)
        if not ok:
            raise HTTPException(status_code=400,
                                detail=f"Bot {data.bot_id} 不在该运行任务中")
        # DB：释放原 assignment（标记 released，保留历史）
        ba = db.query(MapArtBotAssignment).filter(
            MapArtBotAssignment.task_id == task_id,
            MapArtBotAssignment.bot_id == data.bot_id,
        ).first()
        if ba:
            ba.state = "released"
        db.commit()
        return {"task_id": task_id, "bot_id": data.bot_id, "action": "remove"}

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
    cfg = {
        "go": data.go.strip() or "/ehomes mdssj",
        "save": data.save.strip() or "/esethomes dth",
        "return": data.return_.strip() or "/ehomes dth",
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


@router.get("/tasks/{task_id}/blocks/placed")
def get_task_placed_blocks(task_id: str, db: Session = Depends(get_db),
                           user=Depends(require_admin)):
    """P1-5：轻量增量接口——只返回已放置方块，供前端 2D 画布轮询刷新。

    相比全量 blocks（16384+ 条），placed 子集通常远小；前端每 5s 拉一次
    增量涂色，避免画布停留在页面加载快照。
    """
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
