"""任务中心聚合接口（只读）——统一展示地图画建造 + 物流任务。

2026-08-12 新增（实施计划阶段 1）：
- GET /api/tasks/overview：统一任务列表 + 统计 + Bot 执行视角数据
- 只读聚合，登录即可访问（get_current_user）；管理操作仍走各模块原 require_admin 接口
- 前端「任务中心」页（/tasks）数据源
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from vmtools_next.api.deps import get_db, get_current_user
from vmtools_next.data.models.build_map_art import MapArtTask, MapArtBotAssignment
from vmtools_next.data.models.logistics import (
    LogisticsTaskRunModel, LogisticsTaskTemplateModel, MccBotModel,
)
from vmtools_next.core.bot_engine import resolve_bot_engine

router = APIRouter(prefix="/api/tasks", tags=["tasks"])

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
    }


@router.get("/overview")
def tasks_overview(
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    """任务中心聚合：地图画 + 物流统一列表、统计、Bot 执行视角。"""
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

    tasks: list[dict] = []
    for t in map_art_tasks:
        tasks.append(_map_art_to_task(t, assignments_by_task.get(t.task_id, [])))
    for r in logistics_runs:
        tasks.append(_logistics_to_task(
            r,
            template_name_map.get(r.template_id, ""),
            _resolve_engine_safe(db, r.bot_id),
        ))

    # Bot 列表（mcc_bots 统一表，含 MF）+ 引擎
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
        bot_list.append({
            "bot_id": b.bot_id,
            "name": b.name or b.bot_id,
            "status": b.status,
            "engine": engine,
            "busy": b.bot_id in running_bot_ids,
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

    return {
        "tasks": tasks,
        "stats": stats,
        "bots": bot_list,
    }
