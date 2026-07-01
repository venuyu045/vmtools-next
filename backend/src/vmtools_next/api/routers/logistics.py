"""Logistics management API routes.

Provides CRUD for waypoints, drop points, task templates, task runs.
Migrated from vmtools-backend/routers/logistics.py.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import desc

from vmtools_next.api.deps import get_db, get_current_user
from vmtools_next.api.schemas.logistics import (
    WaypointCreate, WaypointUpdate, WaypointResponse,
    DropPointCreate, DropPointUpdate, DropPointResponse,
    TaskTemplateCreate, TaskTemplateUpdate, TaskTemplateResponse,
    TaskRunResponse, TaskLogResponse, TaskStartRequest,
)
from vmtools_next.data.models.logistics import (
    LogisticsWaypointModel, LogisticsDropPointModel,
    LogisticsTaskTemplateModel, LogisticsTaskRunModel, LogisticsTaskLogModel,
)
from vmtools_next.infra.logging import get_logger

logger = get_logger("api.logistics")
router = APIRouter(prefix="/api/logistics", tags=["logistics"])


# ── Waypoints ──────────────────────────────────────────────────────────

@router.get("/waypoints", response_model=list[WaypointResponse])
def list_waypoints(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    q = db.query(LogisticsWaypointModel)
    if user.organization_id:
        q = q.filter(LogisticsWaypointModel.organization_id == user.organization_id)
    items = q.order_by(desc(LogisticsWaypointModel.created_at)).offset((page - 1) * page_size).limit(page_size).all()
    return [_waypoint_to_response(w) for w in items]


@router.get("/waypoints/{waypoint_id}", response_model=WaypointResponse)
def get_waypoint(waypoint_id: str, db: Session = Depends(get_db), user=Depends(get_current_user)):
    w = db.query(LogisticsWaypointModel).filter(LogisticsWaypointModel.waypoint_id == waypoint_id).first()
    if not w:
        raise HTTPException(404, "Waypoint not found")
    return _waypoint_to_response(w)


@router.post("/waypoints", response_model=WaypointResponse)
def create_waypoint(data: WaypointCreate, db: Session = Depends(get_db), user=Depends(get_current_user)):
    w = LogisticsWaypointModel(waypoint_id=str(uuid.uuid4()), **data.model_dump())
    db.add(w)
    db.commit()
    db.refresh(w)
    logger.info("Created waypoint: %s", w.waypoint_id)
    return _waypoint_to_response(w)


@router.put("/waypoints/{waypoint_id}", response_model=WaypointResponse)
def update_waypoint(waypoint_id: str, data: WaypointUpdate, db: Session = Depends(get_db), user=Depends(get_current_user)):
    w = db.query(LogisticsWaypointModel).filter(LogisticsWaypointModel.waypoint_id == waypoint_id).first()
    if not w:
        raise HTTPException(404, "Waypoint not found")
    for k, v in data.model_dump(exclude_unset=True).items():
        setattr(w, k, v)
    db.commit()
    db.refresh(w)
    return _waypoint_to_response(w)


@router.delete("/waypoints/{waypoint_id}")
def delete_waypoint(waypoint_id: str, db: Session = Depends(get_db), user=Depends(get_current_user)):
    w = db.query(LogisticsWaypointModel).filter(LogisticsWaypointModel.waypoint_id == waypoint_id).first()
    if not w:
        raise HTTPException(404, "Waypoint not found")
    db.delete(w)
    db.commit()
    return {"status": "deleted"}


# ── Drop Points ────────────────────────────────────────────────────────

@router.get("/drop-points", response_model=list[DropPointResponse])
def list_drop_points(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    q = db.query(LogisticsDropPointModel)
    if user.organization_id:
        q = q.filter(LogisticsDropPointModel.organization_id == user.organization_id)
    items = q.order_by(desc(LogisticsDropPointModel.created_at)).offset((page - 1) * page_size).limit(page_size).all()
    return [_drop_point_to_response(d) for d in items]


@router.get("/drop-points/{drop_point_id}", response_model=DropPointResponse)
def get_drop_point(drop_point_id: str, db: Session = Depends(get_db), user=Depends(get_current_user)):
    d = db.query(LogisticsDropPointModel).filter(LogisticsDropPointModel.drop_point_id == drop_point_id).first()
    if not d:
        raise HTTPException(404, "Drop point not found")
    return _drop_point_to_response(d)


@router.post("/drop-points", response_model=DropPointResponse)
def create_drop_point(data: DropPointCreate, db: Session = Depends(get_db), user=Depends(get_current_user)):
    d = LogisticsDropPointModel(drop_point_id=str(uuid.uuid4()), **data.model_dump())
    db.add(d)
    db.commit()
    db.refresh(d)
    logger.info("Created drop point: %s", d.drop_point_id)
    return _drop_point_to_response(d)


@router.put("/drop-points/{drop_point_id}", response_model=DropPointResponse)
def update_drop_point(drop_point_id: str, data: DropPointUpdate, db: Session = Depends(get_db), user=Depends(get_current_user)):
    d = db.query(LogisticsDropPointModel).filter(LogisticsDropPointModel.drop_point_id == drop_point_id).first()
    if not d:
        raise HTTPException(404, "Drop point not found")
    for k, v in data.model_dump(exclude_unset=True).items():
        setattr(d, k, v)
    db.commit()
    db.refresh(d)
    return _drop_point_to_response(d)


@router.delete("/drop-points/{drop_point_id}")
def delete_drop_point(drop_point_id: str, db: Session = Depends(get_db), user=Depends(get_current_user)):
    d = db.query(LogisticsDropPointModel).filter(LogisticsDropPointModel.drop_point_id == drop_point_id).first()
    if not d:
        raise HTTPException(404, "Drop point not found")
    db.delete(d)
    db.commit()
    return {"status": "deleted"}


# ── Task Templates ─────────────────────────────────────────────────────

@router.get("/task-templates", response_model=list[TaskTemplateResponse])
def list_templates(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    q = db.query(LogisticsTaskTemplateModel)
    if user.organization_id:
        q = q.filter(LogisticsTaskTemplateModel.organization_id == user.organization_id)
    items = q.order_by(desc(LogisticsTaskTemplateModel.created_at)).offset((page - 1) * page_size).limit(page_size).all()
    return [_template_to_response(t) for t in items]


@router.get("/task-templates/{template_id}", response_model=TaskTemplateResponse)
def get_template(template_id: str, db: Session = Depends(get_db), user=Depends(get_current_user)):
    t = db.query(LogisticsTaskTemplateModel).filter(LogisticsTaskTemplateModel.template_id == template_id).first()
    if not t:
        raise HTTPException(404, "Template not found")
    return _template_to_response(t)


@router.post("/task-templates", response_model=TaskTemplateResponse)
def create_template(data: TaskTemplateCreate, db: Session = Depends(get_db), user=Depends(get_current_user)):
    # Validate waypoint and drop point exist
    wp = db.query(LogisticsWaypointModel).filter(LogisticsWaypointModel.waypoint_id == data.source_waypoint_id).first()
    if not wp:
        raise HTTPException(400, "Source waypoint not found")
    dp = db.query(LogisticsDropPointModel).filter(LogisticsDropPointModel.drop_point_id == data.drop_point_id).first()
    if not dp:
        raise HTTPException(400, "Drop point not found")

    t = LogisticsTaskTemplateModel(template_id=str(uuid.uuid4()), **data.model_dump())
    db.add(t)
    db.commit()
    db.refresh(t)
    logger.info("Created template: %s", t.template_id)
    return _template_to_response(t)


@router.put("/task-templates/{template_id}", response_model=TaskTemplateResponse)
def update_template(template_id: str, data: TaskTemplateUpdate, db: Session = Depends(get_db), user=Depends(get_current_user)):
    t = db.query(LogisticsTaskTemplateModel).filter(LogisticsTaskTemplateModel.template_id == template_id).first()
    if not t:
        raise HTTPException(404, "Template not found")
    for k, v in data.model_dump(exclude_unset=True).items():
        setattr(t, k, v)
    t.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(t)
    return _template_to_response(t)


@router.delete("/task-templates/{template_id}")
def delete_template(template_id: str, db: Session = Depends(get_db), user=Depends(get_current_user)):
    t = db.query(LogisticsTaskTemplateModel).filter(LogisticsTaskTemplateModel.template_id == template_id).first()
    if not t:
        raise HTTPException(404, "Template not found")
    db.delete(t)
    db.commit()
    return {"status": "deleted"}


@router.patch("/task-templates/{template_id}/toggle", response_model=TaskTemplateResponse)
def toggle_template(template_id: str, db: Session = Depends(get_db), user=Depends(get_current_user)):
    t = db.query(LogisticsTaskTemplateModel).filter(LogisticsTaskTemplateModel.template_id == template_id).first()
    if not t:
        raise HTTPException(404, "Template not found")
    t.enabled = not t.enabled
    t.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(t)
    return _template_to_response(t)


# ── Task Runs ──────────────────────────────────────────────────────────

@router.get("/task-runs", response_model=list[TaskRunResponse])
def list_runs(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    status: Optional[str] = None,
    bot_id: Optional[str] = None,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    q = db.query(LogisticsTaskRunModel)
    if status:
        q = q.filter(LogisticsTaskRunModel.status == status)
    if bot_id:
        q = q.filter(LogisticsTaskRunModel.bot_id == bot_id)
    items = q.order_by(desc(LogisticsTaskRunModel.started_at)).offset((page - 1) * page_size).limit(page_size).all()
    return [_run_to_response(r) for r in items]


@router.get("/task-runs/{run_id}", response_model=TaskRunResponse)
def get_run(run_id: str, db: Session = Depends(get_db), user=Depends(get_current_user)):
    r = db.query(LogisticsTaskRunModel).filter(LogisticsTaskRunModel.run_id == run_id).first()
    if not r:
        raise HTTPException(404, "Task run not found")
    return _run_to_response(r)


@router.get("/task-runs/{run_id}/logs", response_model=list[TaskLogResponse])
def get_run_logs(
    run_id: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    items = db.query(LogisticsTaskLogModel).filter(
        LogisticsTaskLogModel.run_id == run_id
    ).order_by(desc(LogisticsTaskLogModel.timestamp)).offset((page - 1) * page_size).limit(page_size).all()
    return [_log_to_response(l) for l in items]


@router.post("/tasks/start", response_model=TaskRunResponse)
def start_task(data: TaskStartRequest, db: Session = Depends(get_db), user=Depends(get_current_user)):
    # Verify template exists and is enabled
    t = db.query(LogisticsTaskTemplateModel).filter(LogisticsTaskTemplateModel.template_id == data.template_id).first()
    if not t:
        raise HTTPException(404, "Template not found")
    if not t.enabled:
        raise HTTPException(400, "Template is disabled")

    run = LogisticsTaskRunModel(
        run_id=str(uuid.uuid4()),
        template_id=data.template_id,
        bot_id=data.bot_id,
        status="running",
        current_state="IDLE",
        progress=0.0,
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    logger.info("Started task run: %s (template=%s, bot=%s)", run.run_id, data.template_id, data.bot_id)
    return _run_to_response(run)


@router.post("/tasks/{run_id}/stop")
def stop_task(run_id: str, db: Session = Depends(get_db), user=Depends(get_current_user)):
    r = db.query(LogisticsTaskRunModel).filter(LogisticsTaskRunModel.run_id == run_id).first()
    if not r:
        raise HTTPException(404, "Task run not found")
    r.status = "cancelled"
    r.finished_at = datetime.now(timezone.utc)
    db.commit()
    return {"run_id": run_id, "status": "cancelled"}


@router.post("/tasks/{run_id}/pause")
def pause_task(run_id: str, db: Session = Depends(get_db), user=Depends(get_current_user)):
    r = db.query(LogisticsTaskRunModel).filter(LogisticsTaskRunModel.run_id == run_id).first()
    if not r:
        raise HTTPException(404, "Task run not found")
    r.status = "paused"
    db.commit()
    return {"run_id": run_id, "status": "paused"}


@router.post("/tasks/{run_id}/resume")
def resume_task(run_id: str, db: Session = Depends(get_db), user=Depends(get_current_user)):
    r = db.query(LogisticsTaskRunModel).filter(LogisticsTaskRunModel.run_id == run_id).first()
    if not r:
        raise HTTPException(404, "Task run not found")
    r.status = "running"
    db.commit()
    return {"run_id": run_id, "status": "running"}


# ── Helpers ────────────────────────────────────────────────────────────

def _waypoint_to_response(w: LogisticsWaypointModel) -> WaypointResponse:
    return WaypointResponse(
        waypoint_id=w.waypoint_id, name=w.name, key=w.key,
        warehouse_fk=w.warehouse_fk,
        container_x=w.container_x, container_y=w.container_y, container_z=w.container_z,
        teleport_command=w.teleport_command, item_name=w.item_name, item_id=w.item_id,
        transfer_slots=w.transfer_slots, wait_after_teleport=w.wait_after_teleport,
        organization_id=w.organization_id,
        created_at=w.created_at.isoformat() if w.created_at else None,
    )


def _drop_point_to_response(d: LogisticsDropPointModel) -> DropPointResponse:
    return DropPointResponse(
        drop_point_id=d.drop_point_id, name=d.name,
        teleport_command=d.teleport_command,
        drop_x=d.drop_x, drop_y=d.drop_y, drop_z=d.drop_z,
        drop_method=d.drop_method,
        container_x=d.container_x, container_y=d.container_y, container_z=d.container_z,
        wait_after_teleport=d.wait_after_teleport,
        organization_id=d.organization_id,
        created_at=d.created_at.isoformat() if d.created_at else None,
    )


def _template_to_response(t: LogisticsTaskTemplateModel) -> TaskTemplateResponse:
    return TaskTemplateResponse(
        template_id=t.template_id, name=t.name,
        source_waypoint_id=t.source_waypoint_id, drop_point_id=t.drop_point_id,
        loop_mode=t.loop_mode, notify_target=t.notify_target,
        notify_start=t.notify_start, notify_complete=t.notify_complete,
        change_slot_after=t.change_slot_after, execution_mode=t.execution_mode,
        script_path=t.script_path, enabled=t.enabled,
        organization_id=t.organization_id,
        created_at=t.created_at.isoformat() if t.created_at else None,
        updated_at=t.updated_at.isoformat() if t.updated_at else None,
    )


def _run_to_response(r: LogisticsTaskRunModel) -> TaskRunResponse:
    return TaskRunResponse(
        run_id=r.run_id, template_id=r.template_id, bot_id=r.bot_id,
        status=r.status, current_state=r.current_state,
        loop_count=r.loop_count, progress=r.progress,
        started_at=r.started_at.isoformat() if r.started_at else None,
        finished_at=r.finished_at.isoformat() if r.finished_at else None,
        error_message=r.error_message,
    )


def _log_to_response(l: LogisticsTaskLogModel) -> TaskLogResponse:
    return TaskLogResponse(
        log_id=l.log_id, run_id=l.run_id,
        timestamp=l.timestamp.isoformat() if l.timestamp else None,
        level=l.level, state=l.state, message=l.message,
        raw_event=l.raw_event,
    )
