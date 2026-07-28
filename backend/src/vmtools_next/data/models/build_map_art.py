"""Map Art build task ORM models.

Tables: map_art_tasks, map_art_materials, map_art_bot_assignments, map_art_block_states

Designed per implementation-plan.md Section 4 (Data Model Design).
These are separate from build.py (3D building state machine).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Column, String, Integer, Float, Boolean, DateTime,
    Text, JSON, Index,
)
from sqlalchemy.orm import relationship

from vmtools_next.data.db import Base


def _gen_id() -> str:
    return uuid.uuid4().hex[:12]


class MapArtTask(Base):
    """Map art build task — 2D single-layer projection construction.

    Unlike BuildTaskModel (18-state 3D building), map art tasks use a
    simpler BuildCoordinator + N×BotBuildLoop model.
    """

    __tablename__ = "map_art_tasks"

    task_id = Column(String(12), primary_key=True, default=_gen_id)
    name = Column(String(128), nullable=False)
    description = Column(Text, default="")

    # Projection metadata
    projection_file_path = Column(String(512), nullable=False)
    projection_name = Column(String(256), default="")
    projection_author = Column(String(128), default="")
    projection_size_x = Column(Integer, default=0)
    projection_size_y = Column(Integer, default=0)
    projection_size_z = Column(Integer, default=0)
    projection_total_blocks = Column(Integer, default=0)

    # Build origin (world coordinates)
    origin_x = Column(Integer, default=0)
    origin_y = Column(Integer, default=0)
    origin_z = Column(Integer, default=0)

    # Status lifecycle: draft → pending → running → completed/failed/cancelled
    status = Column(String(20), default="draft")
    error_message = Column(Text, default="")

    # Aggregate progress
    total_blocks = Column(Integer, default=0)
    placed_blocks = Column(Integer, default=0)
    verified_blocks = Column(Integer, default=0)

    # Timestamps
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc),
                         onupdate=lambda: datetime.now(timezone.utc))

    # Org / user
    organization_id = Column(String(36), nullable=True, index=True)
    created_by = Column(String(64), default="")

    # Relationships
    materials = relationship(
        "MapArtMaterial", back_populates="task",
        cascade="all, delete-orphan",
    )
    bot_assignments = relationship(
        "MapArtBotAssignment", back_populates="task",
        cascade="all, delete-orphan",
    )
    block_states = relationship(
        "MapArtBlockState", back_populates="task",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        Index("idx_mapart_status", "status"),
        Index("idx_mapart_org", "organization_id"),
    )


class MapArtMaterial(Base):
    """Material requirements for a map art task."""

    __tablename__ = "map_art_materials"

    id = Column(Integer, primary_key=True, autoincrement=True)
    task_id = Column(String(12), nullable=False, index=True)

    item_id = Column(String(128), nullable=False)       # e.g. "minecraft:white_wool"
    display_name = Column(String(256), default="")       # "White Wool"
    required_count = Column(Integer, default=0)
    placed_count = Column(Integer, default=0)
    color_hex = Column(String(7), default="")            # "#FFFFFF"

    task = relationship("MapArtTask", back_populates="materials")


class MapArtBotAssignment(Base):
    """Bot assigned to a region of the map art build task."""

    __tablename__ = "map_art_bot_assignments"

    id = Column(Integer, primary_key=True, autoincrement=True)
    task_id = Column(String(12), nullable=False, index=True)
    bot_id = Column(String(64), nullable=False, index=True)
    bot_name = Column(String(128), default="")

    # Region: (x_start, x_end) × (z_start, z_end) — inclusive
    region_x_start = Column(Integer, default=0)
    region_x_end = Column(Integer, default=0)
    region_z_start = Column(Integer, default=0)
    region_z_end = Column(Integer, default=0)

    # Progress within region
    state = Column(String(20), default="idle")  # idle|moving|placing|restocking|waiting|offline|completed
    blocks_placed = Column(Integer, default=0)
    blocks_total = Column(Integer, default=0)
    current_row = Column(Integer, default=-1)            # current Z-row being built
    last_completed_x = Column(Integer, default=-1)       # checkpoint for resume

    # Supply box location
    supply_box_x = Column(Integer, nullable=True)
    supply_box_y = Column(Integer, nullable=True)
    supply_box_z = Column(Integer, nullable=True)

    # Performance
    place_rate = Column(Float, default=0.0)              # blocks/min
    last_update_at = Column(DateTime, nullable=True)

    task = relationship("MapArtTask", back_populates="bot_assignments")

    __table_args__ = (
        Index("idx_mapart_ba_task", "task_id"),
        Index("idx_mapart_ba_bot", "bot_id"),
    )


class MapArtBlockState(Base):
    """Per-block state in the map art build area.

    One row per non-air block in the projection.
    128×128 map art = up to 16384 rows.
    """

    __tablename__ = "map_art_block_states"

    id = Column(Integer, primary_key=True, autoincrement=True)
    task_id = Column(String(12), nullable=False, index=True)

    # World coordinates
    x = Column(Integer, nullable=False)
    y = Column(Integer, nullable=False)
    z = Column(Integer, nullable=False)

    # Block info
    expected_block = Column(String(128), nullable=False)  # e.g. "minecraft:white_wool"
    actual_block = Column(String(128), default="")         # filled after placement verification
    placed = Column(Boolean, default=False)
    verified = Column(Boolean, default=False)

    # Who placed it
    placed_by_bot = Column(String(64), default="")
    placed_at = Column(DateTime, nullable=True)
    verified_at = Column(DateTime, nullable=True)

    task = relationship("MapArtTask", back_populates="block_states")

    __table_args__ = (
        Index("idx_mapart_bs_task_coord", "task_id", "x", "z"),
        {"sqlite_autoincrement": True},
    )
