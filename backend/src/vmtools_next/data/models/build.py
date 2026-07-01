"""Build task ORM models (NEW — not in vmtools-backend).

Tables: build_tasks, build_layers

These track the 18-state BuildStateMachine lifecycle for projection-based
construction tasks driven by MCC MCP PlaceBlock calls.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Column, String, Integer, Boolean, DateTime, Text, ForeignKey, Index
from sqlalchemy.orm import relationship

from vmtools_next.data.db import Base


class BuildTaskModel(Base):
    """A build task instance driven by BuildStateMachine.

    Tracks the 18-state lifecycle: IDLE → ANALYZE_PROJECTION → ... → DONE.
    The nested TAKE_MATERIALS state has its own RestockPhase (7 sub-states).
    """

    __tablename__ = "build_tasks"

    task_id = Column(String, primary_key=True)
    bot_id = Column(String, ForeignKey("mcc_bots.bot_id"), nullable=False)
    projection_file_path = Column(Text, nullable=False)
    projection_name = Column(String, nullable=True)
    origin_x = Column(Integer, default=0, nullable=False)
    origin_y = Column(Integer, default=0, nullable=False)
    origin_z = Column(Integer, default=0, nullable=False)
    total_layers = Column(Integer, default=0, nullable=False)
    current_layer = Column(Integer, default=0, nullable=False)
    layer_height = Column(Integer, default=6, nullable=False)
    current_state = Column(String, default="IDLE", nullable=False)
    previous_state = Column(String, default="IDLE", nullable=False)
    status = Column(String, default="pending", nullable=False)  # pending|running|paused|completed|failed|cancelled
    travel_purpose = Column(String, default="")
    selected_warehouse_id = Column(String, default="")
    restock_in_progress = Column(Boolean, default=False)
    restock_phase = Column(String, default="IDLE")  # IDLE|NAVIGATING|OPENING|READING|EXTRACTING|CLOSING|DONE
    paused = Column(Boolean, default=False)
    error_message = Column(Text, nullable=True)
    started_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)
    organization_id = Column(String, nullable=True, index=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

    __table_args__ = (
        Index("idx_build_tasks_status", "status"),
        Index("idx_build_tasks_bot", "bot_id"),
    )

    layers = relationship("BuildLayerModel", back_populates="task", cascade="all, delete-orphan")


class BuildLayerModel(Base):
    """Per-layer progress for a build task.

    One row per layer (Y-axis slice) of the projection. Tracks block
    placement count, verification missing count, and retry attempts.
    """

    __tablename__ = "build_layers"

    id = Column(Integer, primary_key=True, autoincrement=True)
    task_id = Column(String, ForeignKey("build_tasks.task_id"), nullable=False, index=True)
    layer_index = Column(Integer, nullable=False)
    total_blocks = Column(Integer, default=0, nullable=False)
    placed_blocks = Column(Integer, default=0, nullable=False)
    missing_blocks = Column(Integer, default=0, nullable=False)
    retry_count = Column(Integer, default=0, nullable=False)
    status = Column(String, default="pending", nullable=False)  # pending|building|verifying|completed|failed
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)

    task = relationship("BuildTaskModel", back_populates="layers")
