"""Build task API routes."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional
from sqlalchemy.orm import Session

from vmtools_next.api.deps import get_db, get_current_user
from vmtools_next.data.models.build import BuildTaskModel

router = APIRouter(prefix="/api/build", tags=["build"])


class BuildTaskCreate(BaseModel):
    bot_id: str
    projection_file_path: str
    projection_name: Optional[str] = None
    origin_x: int = 0
    origin_y: int = 0
    origin_z: int = 0
    layer_height: int = 6


class BuildTaskResponse(BaseModel):
    task_id: str
    bot_id: str
    projection_name: Optional[str]
    status: str
    current_state: str
    current_layer: int
    total_layers: int
    error_message: Optional[str]


@router.get("/tasks", response_model=list[BuildTaskResponse])
def list_tasks(db: Session = Depends(get_db), user=Depends(get_current_user)):
    tasks = db.query(BuildTaskModel).all()
    return [BuildTaskResponse(
        task_id=t.task_id, bot_id=t.bot_id, projection_name=t.projection_name,
        status=t.status, current_state=t.current_state,
        current_layer=t.current_layer, total_layers=t.total_layers,
        error_message=t.error_message,
    ) for t in tasks]


@router.post("/tasks", response_model=BuildTaskResponse)
def create_task(data: BuildTaskCreate, db: Session = Depends(get_db),
                user=Depends(get_current_user)):
    task_id = str(uuid.uuid4())
    task = BuildTaskModel(
        task_id=task_id,
        bot_id=data.bot_id,
        projection_file_path=data.projection_file_path,
        projection_name=data.projection_name,
        origin_x=data.origin_x,
        origin_y=data.origin_y,
        origin_z=data.origin_z,
        layer_height=data.layer_height,
        status="pending",
        organization_id=user.organization_id,
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    return BuildTaskResponse(
        task_id=task.task_id, bot_id=task.bot_id, projection_name=task.projection_name,
        status=task.status, current_state=task.current_state,
        current_layer=task.current_layer, total_layers=task.total_layers,
        error_message=task.error_message,
    )


@router.get("/tasks/{task_id}", response_model=BuildTaskResponse)
def get_task(task_id: str, db: Session = Depends(get_db), user=Depends(get_current_user)):
    task = db.query(BuildTaskModel).filter(BuildTaskModel.task_id == task_id).first()
    if not task:
        raise HTTPException(404, "Task not found")
    return BuildTaskResponse(
        task_id=task.task_id, bot_id=task.bot_id, projection_name=task.projection_name,
        status=task.status, current_state=task.current_state,
        current_layer=task.current_layer, total_layers=task.total_layers,
        error_message=task.error_message,
    )


@router.post("/tasks/{task_id}/start")
async def start_task(task_id: str, db: Session = Depends(get_db),
                      user=Depends(get_current_user)):
    task = db.query(BuildTaskModel).filter(BuildTaskModel.task_id == task_id).first()
    if not task:
        raise HTTPException(404, "Task not found")

    from vmtools_next.main import get_task_engine
    engine = get_task_engine()
    if not engine:
        raise HTTPException(503, "Task engine not initialized")

    result = await engine.start_build_task(
        task.bot_id, task.projection_file_path,
        task.origin_x, task.origin_y, task.origin_z
    )
    if result:
        task.status = "running"
        task.started_at = datetime.now(timezone.utc)
        db.commit()
        return {"task_id": task_id, "status": "running"}
    else:
        raise HTTPException(400, "Failed to start build task")


@router.post("/tasks/{task_id}/pause")
async def pause_task(task_id: str, db: Session = Depends(get_db),
                      user=Depends(get_current_user)):
    task = db.query(BuildTaskModel).filter(BuildTaskModel.task_id == task_id).first()
    if not task:
        raise HTTPException(404, "Task not found")
    task.status = "paused"
    task.paused = True
    db.commit()
    return {"task_id": task_id, "status": "paused"}


@router.post("/tasks/{task_id}/resume")
async def resume_task(task_id: str, db: Session = Depends(get_db),
                       user=Depends(get_current_user)):
    task = db.query(BuildTaskModel).filter(BuildTaskModel.task_id == task_id).first()
    if not task:
        raise HTTPException(404, "Task not found")
    task.status = "running"
    task.paused = False
    db.commit()
    return {"task_id": task_id, "status": "running"}


@router.post("/tasks/{task_id}/cancel")
async def cancel_task(task_id: str, db: Session = Depends(get_db),
                       user=Depends(get_current_user)):
    task = db.query(BuildTaskModel).filter(BuildTaskModel.task_id == task_id).first()
    if not task:
        raise HTTPException(404, "Task not found")
    task.status = "cancelled"
    db.commit()
    return {"task_id": task_id, "status": "cancelled"}
