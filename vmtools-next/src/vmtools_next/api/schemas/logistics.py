"""Pydantic schemas for logistics management APIs.

Covers: Waypoint, DropPoint, TaskTemplate, TaskRun, TaskLog CRUD.
Migrated from vmtools-backend/routers/schemas_logistics.py.
"""
from __future__ import annotations

from typing import Optional
from pydantic import BaseModel, Field, field_validator


# ── Waypoint ───────────────────────────────────────────────────────────

class WaypointCreate(BaseModel):
    name: str = Field(..., description="显示名称")
    key: str = Field(default="", description="标识键")
    warehouse_fk: Optional[str] = None
    container_x: int = 0
    container_y: int = 0
    container_z: int = 0
    teleport_command: str = Field(default="", description="传送命令")
    item_name: str = Field(default="", description="物品名称")
    item_id: Optional[str] = None
    transfer_slots: Optional[str] = Field(default=None, description="JSON: [[0,54],[1,55]]")
    wait_after_teleport: int = Field(default=31, ge=0)
    organization_id: Optional[str] = None

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("名称不能为空")
        return v.strip()


class WaypointUpdate(BaseModel):
    name: Optional[str] = None
    key: Optional[str] = None
    warehouse_fk: Optional[str] = None
    container_x: Optional[int] = None
    container_y: Optional[int] = None
    container_z: Optional[int] = None
    teleport_command: Optional[str] = None
    item_name: Optional[str] = None
    item_id: Optional[str] = None
    transfer_slots: Optional[str] = None
    wait_after_teleport: Optional[int] = Field(default=None, ge=0)
    organization_id: Optional[str] = None


class WaypointResponse(BaseModel):
    waypoint_id: str
    name: str
    key: str
    warehouse_fk: Optional[str] = None
    container_x: int
    container_y: int
    container_z: int
    teleport_command: str
    item_name: str
    item_id: Optional[str] = None
    transfer_slots: Optional[str] = None
    wait_after_teleport: int
    organization_id: Optional[str] = None
    created_at: Optional[str] = None


# ── DropPoint ──────────────────────────────────────────────────────────

class DropPointCreate(BaseModel):
    name: str = Field(..., description="显示名称")
    teleport_command: str = Field(default="", description="传送命令")
    drop_x: Optional[int] = None
    drop_y: Optional[int] = None
    drop_z: Optional[int] = None
    drop_method: str = Field(default="drop", description="drop | container")
    container_x: Optional[int] = None
    container_y: Optional[int] = None
    container_z: Optional[int] = None
    wait_after_teleport: int = Field(default=5, ge=0)
    organization_id: Optional[str] = None

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("名称不能为空")
        return v.strip()

    @field_validator("drop_method")
    @classmethod
    def validate_method(cls, v: str) -> str:
        if v not in ("drop", "container"):
            raise ValueError("drop_method 必须是 'drop' 或 'container'")
        return v


class DropPointUpdate(BaseModel):
    name: Optional[str] = None
    teleport_command: Optional[str] = None
    drop_x: Optional[int] = None
    drop_y: Optional[int] = None
    drop_z: Optional[int] = None
    drop_method: Optional[str] = None
    container_x: Optional[int] = None
    container_y: Optional[int] = None
    container_z: Optional[int] = None
    wait_after_teleport: Optional[int] = Field(default=None, ge=0)
    organization_id: Optional[str] = None

    @field_validator("drop_method")
    @classmethod
    def validate_method(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and v not in ("drop", "container"):
            raise ValueError("drop_method 必须是 'drop' 或 'container'")
        return v


class DropPointResponse(BaseModel):
    drop_point_id: str
    name: str
    teleport_command: str
    drop_x: Optional[int] = None
    drop_y: Optional[int] = None
    drop_z: Optional[int] = None
    drop_method: str
    container_x: Optional[int] = None
    container_y: Optional[int] = None
    container_z: Optional[int] = None
    wait_after_teleport: int
    organization_id: Optional[str] = None
    created_at: Optional[str] = None


# ── TaskTemplate ───────────────────────────────────────────────────────

class TaskTemplateCreate(BaseModel):
    name: str = Field(..., description="任务名称")
    source_waypoint_id: str = Field(..., description="取货路径点 ID")
    drop_point_id: str = Field(..., description="投放点 ID")
    loop_mode: str = Field(default="once", description="once | loop")
    notify_target: Optional[str] = None
    notify_start: bool = False
    notify_complete: bool = True
    change_slot_after: int = Field(default=1, ge=0, le=8)
    execution_mode: str = Field(default="script", description="script | command | hybrid")
    script_path: Optional[str] = None
    enabled: bool = True
    organization_id: Optional[str] = None

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("名称不能为空")
        return v.strip()

    @field_validator("loop_mode")
    @classmethod
    def validate_loop_mode(cls, v: str) -> str:
        if v not in ("once", "loop"):
            raise ValueError("loop_mode 必须是 'once' 或 'loop'")
        return v

    @field_validator("execution_mode")
    @classmethod
    def validate_exec_mode(cls, v: str) -> str:
        if v not in ("script", "command", "hybrid"):
            raise ValueError("execution_mode 必须是 'script'、'command' 或 'hybrid'")
        return v


class TaskTemplateUpdate(BaseModel):
    name: Optional[str] = None
    source_waypoint_id: Optional[str] = None
    drop_point_id: Optional[str] = None
    loop_mode: Optional[str] = None
    notify_target: Optional[str] = None
    notify_start: Optional[bool] = None
    notify_complete: Optional[bool] = None
    change_slot_after: Optional[int] = Field(default=None, ge=0, le=8)
    execution_mode: Optional[str] = None
    script_path: Optional[str] = None
    enabled: Optional[bool] = None


class TaskTemplateResponse(BaseModel):
    template_id: str
    name: str
    source_waypoint_id: str
    drop_point_id: str
    loop_mode: str
    notify_target: Optional[str] = None
    notify_start: bool
    notify_complete: bool
    change_slot_after: int
    execution_mode: str
    script_path: Optional[str] = None
    enabled: bool
    organization_id: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


# ── TaskRun / TaskLog ─────────────────────────────────────────────────

class TaskRunResponse(BaseModel):
    run_id: str
    template_id: str
    bot_id: str
    status: str
    current_state: str
    loop_count: int
    progress: float
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    error_message: Optional[str] = None


class TaskLogResponse(BaseModel):
    log_id: int
    run_id: str
    timestamp: Optional[str] = None
    level: str
    state: str
    message: str
    raw_event: Optional[str] = None


class TaskStartRequest(BaseModel):
    template_id: str
    bot_id: str


class TaskControlRequest(BaseModel):
    action: str = Field(..., description="start | stop | pause | resume")
    run_id: Optional[str] = None
    template_id: Optional[str] = None
    bot_id: Optional[str] = None
