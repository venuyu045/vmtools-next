"""任务中心聚合接口（只读）——统一展示地图画建造 + 物流任务。

2026-08-12 新增（实施计划阶段 1）：
- GET /api/tasks/overview：统一任务列表 + 统计 + Bot 执行视角数据
- 只读聚合，登录即可访问（get_current_user）；管理操作仍走各模块原 require_admin 接口
- 前端「任务中心」页（/tasks）数据源
"""
from __future__ import annotations

import json as _json
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from vmtools_next.api.deps import get_db, get_current_user, get_optional_user, require_admin
from vmtools_next.data.models.build_map_art import MapArtTask, MapArtBotAssignment
from vmtools_next.data.models.logistics import (
    LogisticsTaskRunModel, LogisticsTaskTemplateModel, MccBotModel,
)
from vmtools_next.core.bot_engine import resolve_bot_engine
from vmtools_next.infra.logging import get_logger

logger = get_logger("tasks_api")
router = APIRouter(prefix="/api/tasks", tags=["tasks"])


class ManualWorkUpdate(BaseModel):
    working: bool
    name: str = ""


class ScheduledTaskCreate(BaseModel):
    name: str
    task_type: str            # scan | logistics | map_art
    target_id: str
    bot_ids: list[str]
    schedule_kind: str        # once | daily | weekly
    run_at: Optional[str] = None   # once：ISO 时间
    schedule_time: str = ""        # daily/weekly：HH:MM
    schedule_weekday: int = 0      # weekly：0=周一 ~ 6=周日
    auto_manage: bool = True       # 执行时自动上线 bot、任务完成自动下线（2026-08-13）


class ScheduledTaskUpdate(BaseModel):
    enabled: Optional[bool] = None
    name: Optional[str] = None
    auto_manage: Optional[bool] = None


def _as_utc_naive(dt) -> Optional[datetime]:
    """统一转为 naive UTC（SQLite 存储的 datetime 无时区，避免 aware/naive 相减报错）。"""
    if dt is None:
        return None
    if dt.tzinfo is not None:
        return dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def _duration_seconds(started_at, finished_at) -> Optional[int]:
    s = _as_utc_naive(started_at)
    if s is None:
        return None
    # 2026-10-15 审查修复：datetime.utcnow() 在 Python 3.12 已标记弃用，
    # 且语义不如显式 aware→naive 转换清晰，统一改为 now(timezone.utc) 归一化。
    e = _as_utc_naive(finished_at) or datetime.now(timezone.utc).replace(tzinfo=None)
    return max(0, int((e - s).total_seconds()))

# ── 状态文案 ──────────────────────────────────────────────

_MAP_ART_STATUS_LABEL = {
    "draft": "草稿",
    "pending": "排队中",
    "running": "运行中",
    "paused": "已暂停",
    "completed": "已完成",
    "failed": "失败",
    "cancelled": "已取消",
}

_LOGISTICS_STATUS_LABEL = {
    "pending": "排队中",
    "running": "运行中",
    "paused": "已暂停",
    "completed": "已完成",
    "failed": "失败",
    "cancelled": "已取消",
}

_SCAN_STATUS_LABEL = {
    "pending": "排队中",
    "running": "运行中",
    "paused": "已暂停",
    "completed": "已完成",
    "failed": "失败",
    "cancelled": "已取消",
}


def _iso(dt) -> Optional[str]:
    return dt.isoformat() if dt else None


# ── 地图画任务 → 统一结构 ────────────────────────────────

def _map_art_to_task(t: MapArtTask, assignments: list[MapArtBotAssignment]) -> dict:
    return {
        "type": "map_art",
        "id": t.task_id,
        "name": t.name or "未命名",
        "status": t.status,
        "status_label": _MAP_ART_STATUS_LABEL.get(t.status, t.status),
        "progress": {
            "placed": t.placed_blocks or 0,
            "total": t.total_blocks or 0,
        },
        "bots": [
            {
                "bot_id": a.bot_id,
                "bot_name": a.bot_name or a.bot_id,
                "state": a.state,
                "blocks_placed": a.blocks_placed or 0,
                "blocks_total": a.blocks_total or 0,
            }
            for a in assignments
        ],
        "engine": "mineflayer",  # 地图画仅支持 MF
        "detail_url": f"/map-art/{t.task_id}",
        "created_at": _iso(t.created_at),
        "started_at": _iso(t.started_at),
        "finished_at": _iso(t.completed_at),
        "duration_seconds": _duration_seconds(t.started_at, t.completed_at),
    }


# ── 物流任务 → 统一结构 ──────────────────────────────────

def _resolve_engine_safe(db: Session, bot_id: str) -> str:
    """解析 bot 引擎，失败兜底 'unknown'（避免 db 缺失/查询异常）。"""
    if not bot_id:
        return "unknown"
    try:
        return resolve_bot_engine(bot_id, db)
    except Exception:
        return "unknown"


def _logistics_to_task(r: LogisticsTaskRunModel, template_name: str, engine: str) -> dict:
    return {
        "type": "logistics",
        "id": r.run_id,
        "name": template_name or "未命名物流任务",
        "status": r.status,
        "status_label": _LOGISTICS_STATUS_LABEL.get(r.status, r.status),
        "progress": {
            "percent": round((r.progress or 0.0) * 100, 1),
        },
        "bots": [
            {"bot_id": r.bot_id, "bot_name": r.bot_id, "state": r.current_state or "IDLE"},
        ],
        "engine": engine,
        "detail_url": "/logistics/runs",
        "current_state": r.current_state,
        "loop_count": r.loop_count or 0,
        "error_message": r.error_message,
        "created_at": _iso(r.started_at),
        "started_at": _iso(r.started_at),
        "finished_at": _iso(r.finished_at),
        "duration_seconds": _duration_seconds(r.started_at, r.finished_at),
    }


@router.get("/overview")
def tasks_overview(
    db: Session = Depends(get_db),
    user=Depends(get_optional_user),
):
    """任务中心聚合：地图画 + 物流 + 仓库扫描统一列表、统计、Bot 执行视角。"""
    # 地图画任务（含 bot 分配，取最近 100 条）
    map_art_tasks = db.query(MapArtTask).order_by(
        MapArtTask.created_at.desc()
    ).limit(100).all()
    assignments_by_task: dict[str, list[MapArtBotAssignment]] = {}
    if map_art_tasks:
        task_ids = [t.task_id for t in map_art_tasks]
        rows = db.query(MapArtBotAssignment).filter(
            MapArtBotAssignment.task_id.in_(task_ids)
        ).all()
        for a in rows:
            assignments_by_task.setdefault(a.task_id, []).append(a)

    # 物流任务（含模板名，取最近 100 条）
    logistics_runs = db.query(LogisticsTaskRunModel).order_by(
        LogisticsTaskRunModel.started_at.desc()
    ).limit(100).all()
    template_name_map: dict[str, str] = {}
    if logistics_runs:
        tpl_ids = {r.template_id for r in logistics_runs}
        tpls = db.query(LogisticsTaskTemplateModel).filter(
            LogisticsTaskTemplateModel.template_id.in_(tpl_ids)
        ).all()
        template_name_map = {t.template_id: t.name for t in tpls}

    # 仓库扫描任务（2026-08-13 补：任务中心此前漏掉扫描，扫描中 bot 显示空闲）
    from vmtools_next.data.models.warehouse import ScanQueueModel, WarehouseModel
    scan_runs = db.query(ScanQueueModel).order_by(
        ScanQueueModel.created_at.desc()
    ).limit(100).all()
    wh_name_map: dict[str, str] = {}
    if scan_runs:
        wh_ids = {s.warehouse_id for s in scan_runs}
        for w in db.query(WarehouseModel).filter(
                WarehouseModel.warehouse_id.in_(wh_ids)).all():
            wh_name_map[w.warehouse_id] = w.name or w.warehouse_id

    tasks: list[dict] = []
    for t in map_art_tasks:
        tasks.append(_map_art_to_task(t, assignments_by_task.get(t.task_id, [])))
    for r in logistics_runs:
        tasks.append(_logistics_to_task(
            r,
            template_name_map.get(r.template_id, ""),
            _resolve_engine_safe(db, r.bot_id),
        ))
    for s in scan_runs:
        tasks.append({
            "type": "scan",
            "id": s.queue_id,
            "name": f"仓库扫描·{wh_name_map.get(s.warehouse_id, s.warehouse_id)}",
            "status": s.status,
            "status_label": _SCAN_STATUS_LABEL.get(s.status, s.status),
            "progress": {"percent": round((s.progress or 0.0) * 100, 1)},
            "bots": [{"bot_id": s.bot_id, "bot_name": s.bot_id}],
            "engine": "mineflayer",
            "detail_url": "/warehouses",
            "created_at": _iso(s.created_at),
            "started_at": _iso(s.started_at),
            "finished_at": _iso(s.finished_at),
            "duration_seconds": _duration_seconds(s.started_at, s.finished_at),
            # 扫描细节（任务中心「进度」列展示，2026-08-13）
            "items_scanned": s.items_scanned or 0,
            "scanned_containers": s.scanned_containers or 0,
            "total_containers": s.total_containers or 0,
            "failed_containers": s.failed_containers or 0,
            "error_message": s.error,
        })

    # Bot 列表（2026-08-13 任务中心仅服务 MF：只返回 mineflayer 引擎的 bot）
    from vmtools_next.core.bot_work import get_manual_work
    bots = db.query(MccBotModel).all()
    bot_list = []
    running_bot_ids: set[str] = set()
    for tk in tasks:
        if tk["status"] == "running":
            for b in tk["bots"]:
                running_bot_ids.add(b["bot_id"])
    for b in bots:
        try:
            engine = resolve_bot_engine(b.bot_id, db)
        except Exception:
            engine = "unknown"
        if engine != "mineflayer":
            continue
        manual = get_manual_work(db, b.bot_id)
        bot_list.append({
            "bot_id": b.bot_id,
            "name": b.name or b.bot_id,
            "status": b.status,
            "engine": engine,
            "busy": b.bot_id in running_bot_ids or manual is not None,
            "manual": manual,  # 手动标记「工作中」（任务中心 Bot 卡片展示）
        })

    # 统计
    stats = {
        "running": sum(1 for t in tasks if t["status"] == "running"),
        "queued": sum(1 for t in tasks if t["status"] == "pending"),
        "completed": sum(1 for t in tasks if t["status"] == "completed"),
        "failed": sum(1 for t in tasks if t["status"] in ("failed", "cancelled")),
        "bot_total": len(bot_list),
        "bot_online": sum(1 for b in bot_list if b["status"] == "online"),
        "bot_idle": sum(1 for b in bot_list if b["status"] == "online" and not b["busy"]),
    }

    # ⚠️ 2026-10-19 审查修复（中等）：访客可见此接口后，error_message 会泄露内部实现细节
    #   （如 "未发现容器（zone 为空且 scan_nearby_blocks 无结果）" 暴露扫描器内部逻辑、
    #   路径、配置项名）。访客统一抹掉错误详情，登录用户保持原样。
    if user is None:
        for tk in tasks:
            if "error_message" in tk:
                tk["error_message"] = None

    return {
        "tasks": tasks,
        "stats": stats,
        "bots": bot_list,
    }


# ── 任务管理：手动标记「工作中」（2026-08-13） ──────────────────
# 管理栏「任务管理」页数据源与写入接口。手动标记跨上下线保持；
# 被标记 bot 不会被自动调度派活（地图画/物流/扫描入口统一拦截）。


@router.get("/manual-work")
def list_manual_work(
    db: Session = Depends(get_db),
    user=Depends(require_admin),
):
    """任务管理页：所有 MF bot + 手动工作标记 + 当前系统工作。"""
    from vmtools_next.data.models.mcc_remote import MccInstanceModel
    from vmtools_next.core.bot_work import get_manual_work
    from vmtools_next.api.routers.mcc_bot import _get_bot_current_task

    bots = db.query(MccBotModel).all()
    instances = db.query(MccInstanceModel).filter(
        MccInstanceModel.deleted_at.is_(None),
    ).all()
    inst_by_bot = {i.bot_id: i for i in instances if i.bot_id}

    result = []
    for b in bots:
        inst = inst_by_bot.get(b.bot_id)
        engine = (getattr(inst, "bot_engine", None) or "mcc") if inst else "mcc"
        if engine != "mineflayer":
            continue
        result.append({
            "bot_id": b.bot_id,
            "name": b.name or b.bot_id,
            "status": b.status,  # online/offline/connecting/error
            "manual": get_manual_work(db, b.bot_id),
            "system_task": _get_bot_current_task(db, b.bot_id),
        })
    return {"bots": result}


@router.put("/manual-work/{bot_id}")
def update_manual_work(
    bot_id: str,
    data: ManualWorkUpdate,
    db: Session = Depends(get_db),
    user=Depends(require_admin),
):
    """设置 bot 的手动工作标记。working=True 时 name 必填。"""
    from vmtools_next.core.bot_work import set_manual_work
    try:
        saved = set_manual_work(db, bot_id, data.working, data.name)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    return saved


# ── 定时任务（2026-08-13 任务管理页） ──────────────────────────
# 自定义何时、哪些 bot、做什么任务（仓库扫描/物流/地图画启动），
# 到点由 ScheduledTaskScheduler 自动调度执行；被手动标记「工作中」的 bot 自动跳过。

_WEEKDAY_NAMES = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]


def _scheduled_to_dict(t) -> dict:
    return {
        "id": t.id,
        "name": t.name,
        "task_type": t.task_type,
        "target_id": t.target_id,
        "target_name": t.target_name,
        "bot_ids": _json.loads(t.bot_ids or "[]"),
        "schedule_kind": t.schedule_kind,
        "run_at": _iso(t.run_at),
        "schedule_time": t.schedule_time,
        "schedule_weekday": t.schedule_weekday,
        "schedule_text": _schedule_text(t),
        "enabled": t.enabled,
        "auto_manage": bool(getattr(t, "auto_manage", True)),
        "last_run_at": _iso(t.last_run_at),
        "created_at": _iso(t.created_at),
    }


def _schedule_text(t) -> str:
    if t.schedule_kind == "once":
        return f"一次性 · {_iso(t.run_at) or '?'}"
    if t.schedule_kind == "weekly":
        return f"每周{_WEEKDAY_NAMES[t.schedule_weekday or 0] if 0 <= (t.schedule_weekday or 0) < 7 else '?'} {t.schedule_time}"
    return f"每天 {t.schedule_time}"


def _resolve_target_name(db: Session, task_type: str, target_id: str) -> str:
    try:
        if task_type == "scan":
            from vmtools_next.data.models.warehouse import WarehouseModel
            w = db.query(WarehouseModel).filter(
                WarehouseModel.warehouse_id == target_id).first()
            return (w.name or w.warehouse_id) if w else target_id
        if task_type == "logistics":
            t = db.query(LogisticsTaskTemplateModel).filter(
                LogisticsTaskTemplateModel.template_id == target_id).first()
            return t.name if t else target_id
        if task_type == "map_art":
            t = db.query(MapArtTask).filter(MapArtTask.task_id == target_id).first()
            return (t.name or target_id) if t else target_id
    except Exception:
        pass
    return target_id


@router.get("/scheduled")
def list_scheduled_tasks(
    db: Session = Depends(get_db),
    user=Depends(require_admin),
):
    """定时任务列表（任务管理页）。"""
    from vmtools_next.data.models.scheduled_task import ScheduledTaskModel
    rows = db.query(ScheduledTaskModel).order_by(
        ScheduledTaskModel.created_at.desc()).all()
    return {"tasks": [_scheduled_to_dict(t) for t in rows]}


@router.post("/scheduled")
def create_scheduled_task(
    data: ScheduledTaskCreate,
    db: Session = Depends(get_db),
    user=Depends(require_admin),
):
    """创建定时任务。校验调度参数合法性。"""
    from vmtools_next.data.models.scheduled_task import ScheduledTaskModel
    from datetime import datetime as _dt

    name = (data.name or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="任务名称不能为空")
    if data.task_type not in ("scan", "logistics", "map_art"):
        raise HTTPException(status_code=400, detail="不支持的任务类型")
    if not data.bot_ids:
        raise HTTPException(status_code=400, detail="请至少选择一个 bot")
    if data.schedule_kind not in ("once", "daily", "weekly"):
        raise HTTPException(status_code=400, detail="不支持的调度方式")

    run_at = None
    if data.schedule_kind == "once":
        if not data.run_at:
            raise HTTPException(status_code=400, detail="一次性任务必须指定执行时间")
        try:
            run_at = _dt.fromisoformat(data.run_at.replace("Z", "+00:00"))
        except ValueError as e:
            raise HTTPException(status_code=400, detail="执行时间格式不正确") from e
    else:
        if not data.schedule_time or len(data.schedule_time) != 5 or data.schedule_time[2] != ":":
            raise HTTPException(status_code=400, detail="请选择执行时间（HH:MM）")
        try:
            hh, mm = data.schedule_time.split(":")
            int(hh), int(mm)
            if not (0 <= int(hh) <= 23 and 0 <= int(mm) <= 59):
                raise ValueError
        except Exception as e:
            raise HTTPException(status_code=400, detail="执行时间格式不正确") from e
        if data.schedule_kind == "weekly" and not (0 <= data.schedule_weekday <= 6):
            raise HTTPException(status_code=400, detail="星期取值 0~6（周一到周日）")

    target_name = _resolve_target_name(db, data.task_type, data.target_id)
    task = ScheduledTaskModel(
        name=name,
        task_type=data.task_type,
        target_id=data.target_id,
        target_name=target_name,
        bot_ids=_json.dumps(data.bot_ids, ensure_ascii=False),
        schedule_kind=data.schedule_kind,
        run_at=run_at,
        schedule_time=data.schedule_time,
        schedule_weekday=data.schedule_weekday,
        enabled=True,
        auto_manage=data.auto_manage,
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    logger.info("Scheduled task created: {} ({}, {})", task.id[:8], name, data.task_type)
    return _scheduled_to_dict(task)


@router.put("/scheduled/{task_id}")
def update_scheduled_task(
    task_id: str,
    data: ScheduledTaskUpdate,
    db: Session = Depends(get_db),
    user=Depends(require_admin),
):
    """启用/停用或改名定时任务。"""
    from vmtools_next.data.models.scheduled_task import ScheduledTaskModel
    t = db.query(ScheduledTaskModel).filter(ScheduledTaskModel.id == task_id).first()
    if not t:
        raise HTTPException(status_code=404, detail="定时任务不存在")
    if data.enabled is not None:
        t.enabled = data.enabled
    if data.name is not None:
        n = data.name.strip()
        if not n:
            raise HTTPException(status_code=400, detail="任务名称不能为空")
        t.name = n
    if data.auto_manage is not None:
        t.auto_manage = data.auto_manage
    db.commit()
    db.refresh(t)
    return _scheduled_to_dict(t)


@router.delete("/scheduled/{task_id}")
def delete_scheduled_task(
    task_id: str,
    db: Session = Depends(get_db),
    user=Depends(require_admin),
):
    from vmtools_next.data.models.scheduled_task import ScheduledTaskModel
    t = db.query(ScheduledTaskModel).filter(ScheduledTaskModel.id == task_id).first()
    if not t:
        raise HTTPException(status_code=404, detail="定时任务不存在")
    db.delete(t)
    db.commit()
    return {"ok": True}
