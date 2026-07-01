"""MCC logistics ORM models (migrated from vmtools-backend models_logistics.py).

Tables: mcc_bots, logistics_waypoints, logistics_drop_points,
        logistics_task_templates, logistics_task_runs, logistics_task_logs
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Column, String, Integer, Float, DateTime, Text, Boolean, Index

from vmtools_next.data.db import Base


class MccBotModel(Base):
    """A registered MCC Bot instance.

    Records connection info (WebSocket or MCP endpoint), MC account info,
    live runtime status, and the currently executing task run (if any).
    """

    __tablename__ = "mcc_bots"

    bot_id = Column(String, primary_key=True)
    name = Column(String, default="", nullable=False)
    ws_host = Column(String, default="127.0.0.1", nullable=False)
    ws_port = Column(Integer, default=8043, nullable=False)
    ws_password = Column(String, default="", nullable=False)
    mc_username = Column(String, default="", nullable=False)
    mc_account_type = Column(String, default="offline", nullable=False)  # microsoft | offline
    mc_server_host = Column(String, default="", nullable=False)
    mc_server_port = Column(Integer, default=25565, nullable=False)
    status = Column(String, default="offline", nullable=False)  # offline|connecting|online|error
    last_seen = Column(DateTime, nullable=True)
    current_location = Column(Text, nullable=True)  # JSON: {"x":..,"y":..,"z":..}
    current_health = Column(Float, default=20.0, nullable=False)
    current_food = Column(Integer, default=20, nullable=False)
    current_task_run_id = Column(String, nullable=True)
    current_build_task_id = Column(String, nullable=True)  # NEW: link to build_tasks
    organization_id = Column(String, nullable=True, index=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

    __table_args__ = (
        Index("idx_mcc_bots_status", "status"),
        Index("idx_mcc_bots_org", "organization_id"),
    )


class LogisticsWaypointModel(Base):
    """A pickup waypoint: named location with container and teleport command."""

    __tablename__ = "logistics_waypoints"

    waypoint_id = Column(String, primary_key=True)
    name = Column(String, default="", nullable=False)
    key = Column(String, default="", nullable=False)
    warehouse_fk = Column(String, nullable=True, index=True)
    container_x = Column(Integer, default=0, nullable=False)
    container_y = Column(Integer, default=0, nullable=False)
    container_z = Column(Integer, default=0, nullable=False)
    teleport_command = Column(String, default="", nullable=False)
    item_name = Column(String, default="", nullable=False)
    item_id = Column(String, nullable=True)
    transfer_slots = Column(Text, nullable=True)  # JSON: [[0,54],[1,55],...]
    wait_after_teleport = Column(Integer, default=31, nullable=False)
    organization_id = Column(String, nullable=True, index=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

    __table_args__ = (
        Index("idx_logistics_waypoints_org", "organization_id"),
        Index("idx_logistics_waypoints_key", "key"),
    )


class LogisticsDropPointModel(Base):
    """A drop point: where items are deposited after transport."""

    __tablename__ = "logistics_drop_points"

    drop_point_id = Column(String, primary_key=True)
    name = Column(String, default="", nullable=False)
    teleport_command = Column(String, default="", nullable=False)
    drop_x = Column(Integer, nullable=True)
    drop_y = Column(Integer, nullable=True)
    drop_z = Column(Integer, nullable=True)
    drop_method = Column(String, default="drop", nullable=False)  # drop | container
    container_x = Column(Integer, nullable=True)
    container_y = Column(Integer, nullable=True)
    container_z = Column(Integer, nullable=True)
    wait_after_teleport = Column(Integer, default=5, nullable=False)
    organization_id = Column(String, nullable=True, index=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

    __table_args__ = (
        Index("idx_logistics_drop_points_org", "organization_id"),
    )


class LogisticsTaskTemplateModel(Base):
    """A reusable freight task template."""

    __tablename__ = "logistics_task_templates"

    template_id = Column(String, primary_key=True)
    name = Column(String, default="", nullable=False)
    source_waypoint_id = Column(String, nullable=False, index=True)
    drop_point_id = Column(String, nullable=False, index=True)
    loop_mode = Column(String, default="once", nullable=False)  # once | loop
    notify_target = Column(String, nullable=True)
    notify_start = Column(Boolean, default=False, nullable=False)
    notify_complete = Column(Boolean, default=True, nullable=False)
    change_slot_after = Column(Integer, default=1, nullable=False)
    execution_mode = Column(String, default="script", nullable=False)  # script | command | hybrid
    script_path = Column(String, nullable=True)
    enabled = Column(Boolean, default=True, nullable=False)
    organization_id = Column(String, nullable=True, index=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = Column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    __table_args__ = (
        Index("idx_logistics_task_templates_org", "organization_id"),
        Index("idx_logistics_task_templates_enabled", "enabled"),
    )


class LogisticsTaskRunModel(Base):
    """A single execution instance of a task template."""

    __tablename__ = "logistics_task_runs"

    run_id = Column(String, primary_key=True)
    template_id = Column(String, nullable=False, index=True)
    bot_id = Column(String, nullable=False, index=True)
    status = Column(String, default="pending", nullable=False)  # pending|running|paused|completed|failed|cancelled
    current_state = Column(String, default="IDLE", nullable=False)
    loop_count = Column(Integer, default=0, nullable=False)
    started_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    finished_at = Column(DateTime, nullable=True)
    error_message = Column(Text, nullable=True)
    progress = Column(Float, default=0.0, nullable=False)

    __table_args__ = (
        Index("idx_logistics_task_runs_status", "status"),
        Index("idx_logistics_task_runs_bot", "bot_id"),
    )


class LogisticsTaskLogModel(Base):
    """A single log entry produced during a task run."""

    __tablename__ = "logistics_task_logs"

    log_id = Column(Integer, primary_key=True, autoincrement=True)
    run_id = Column(String, nullable=False, index=True)
    timestamp = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    level = Column(String, default="info", nullable=False)  # info|warn|error|debug
    state = Column(String, default="", nullable=False)
    message = Column(Text, default="", nullable=False)
    raw_event = Column(Text, nullable=True)

    __table_args__ = (
        Index("idx_logistics_task_logs_run", "run_id"),
        Index("idx_logistics_task_logs_run_ts", "run_id", "timestamp"),
    )


class OperationLogModel(Base):
    """Persistent operation log for automation actions.

    Records build, restock, scan, teleport, and error events with
    bot context and duration for monitoring and debugging.
    """

    __tablename__ = "operation_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    operation_type = Column(String, nullable=False, index=True)  # scan|restock|build|teleport|pathing|error
    bot_id = Column(String, default="", nullable=False, index=True)
    warehouse_id = Column(String, default="", nullable=False)
    details = Column(Text, default="", nullable=False)
    success = Column(Boolean, default=True, nullable=False)
    duration_ms = Column(Integer, default=0, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

    __table_args__ = (
        Index("idx_operation_logs_type", "operation_type"),
        Index("idx_operation_logs_bot", "bot_id"),
        Index("idx_operation_logs_created", "created_at"),
    )
