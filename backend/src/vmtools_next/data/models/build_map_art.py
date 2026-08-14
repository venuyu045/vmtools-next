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
    Text, ForeignKey, Index,
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

    # 投影朝向（2026-08-14）：绕 Y 轴顺时针旋转次数（0/1/2/3 = 0°/90°/180°/270°）。
    # 解析时对投影局部坐标统一旋转后落库，前端预览/建造均使用旋转后坐标。
    rotation = Column(Integer, default=0)

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

    # 补货配置（2026-08-14）：JSON 字符串，形如
    # {"go":"/ehomes mdssj","save":"/esethomes dth","return":"/ehomes dth"}
    # go=前往补给点指令 / save=暂存当前位置指令 / return=返回工作位置指令（均可自定义）
    supply_config = Column(Text, default="")

    # 食物配置（2026-08-14 模块A）：JSON，形如
    # {"item_id":"minecraft:cooked_porkchop","go_command":"/res tp lixiangxiang.qwp",
    #  "wait_after_go_ms":5000,"eat_threshold_food":15,"eat_threshold_health":15}
    food_config = Column(Text, default="")

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
    food_boxes = relationship(
        "MapArtFoodBox", back_populates="task",
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
    task_id = Column(String(12), ForeignKey("map_art_tasks.task_id", ondelete="CASCADE"), nullable=False, index=True)

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
    task_id = Column(String(12), ForeignKey("map_art_tasks.task_id", ondelete="CASCADE"), nullable=False, index=True)
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


class MapArtSupplyBox(Base):
    """补货潜影盒配置（2026-08-14）：每种材料对应 1~N 个潜影盒坐标。

    bot 补货时按 sort_order 顺序取货：寻路/传送至坐标附近 → 打开 → 取一组(64) →
    取空则尝试下一个坐标。坐标填世界坐标（玩家站在该坐标附近可交互）。
    """

    __tablename__ = "map_art_supply_boxes"

    id = Column(Integer, primary_key=True, autoincrement=True)
    task_id = Column(String(12), ForeignKey("map_art_tasks.task_id", ondelete="CASCADE"), nullable=False, index=True)
    item_id = Column(String(128), nullable=False)  # "minecraft:white_wool"
    x = Column(Integer, nullable=False)
    y = Column(Integer, nullable=False)
    z = Column(Integer, nullable=False)
    sort_order = Column(Integer, default=0)  # 同一材料多个潜影盒的取货顺序

    __table_args__ = (
        Index("idx_mapart_sb_task_item", "task_id", "item_id"),
    )


class MapArtSupplyTemplate(Base):
    """补货潜影盒模板（2026-08-14 二期）：可复用的材料↔潜影盒坐标配置。

    用户为一批同类地图画（如纯混凝土系列）配好一套潜影盒坐标后存为模板，
    新任务可一键导入（apply 时按任务实际材料交集过滤）。
    """

    __tablename__ = "map_art_supply_templates"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(128), nullable=False, index=True)
    # JSON：[{"item_id":"minecraft:white_concrete","boxes":[{"x":..,"y":..,"z":..},...]}, ...]
    items_json = Column(Text, default="[]")
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc),
                         onupdate=lambda: datetime.now(timezone.utc))


class MapArtSupplyWarehouse(Base):
    """全局补货仓库（2026-08-14 三期）：材料 → 潜影盒坐标映射（全局一份）。

    用户直接设定"某种材料放在哪个潜影盒"，任何地图画任务建造补货时
    自动按材料复用（coordinator 加载任务级配置后合并全局仓库）。
    """

    __tablename__ = "map_art_supply_warehouse"

    id = Column(Integer, primary_key=True, autoincrement=True)
    item_id = Column(String(128), nullable=False, unique=True, index=True)  # "minecraft:white_concrete"
    # JSON：[{"x":..,"y":..,"z":..}, ...]
    boxes_json = Column(Text, default="[]")
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc),
                         onupdate=lambda: datetime.now(timezone.utc))


class MapArtFoodBox(Base):
    """食物潜影盒配置（2026-08-14 模块A）：猪排仓库潜影盒坐标。

    与材料潜影盒分离：食物仓库指令不同（/res tp lixiangxiang.qwp），
    且需等待 5s 才能寻路（指令自带 3s 延迟）。
    """

    __tablename__ = "map_art_food_boxes"

    id = Column(Integer, primary_key=True, autoincrement=True)
    task_id = Column(String(12), ForeignKey("map_art_tasks.task_id", ondelete="CASCADE"), nullable=False, index=True)
    item_id = Column(String(128), nullable=False, default="minecraft:cooked_porkchop")
    x = Column(Integer, nullable=False)
    y = Column(Integer, nullable=False)
    z = Column(Integer, nullable=False)
    sort_order = Column(Integer, default=0)

    task = relationship("MapArtTask", back_populates="food_boxes")

    __table_args__ = (
        Index("idx_mapart_fb_task_item", "task_id", "item_id"),
    )


class MapArtBlockState(Base):
    """Per-block state in the map art build area.

    One row per non-air block in the projection.
    128×128 map art = up to 16384 rows.
    """

    __tablename__ = "map_art_block_states"

    id = Column(Integer, primary_key=True, autoincrement=True)
    task_id = Column(String(12), ForeignKey("map_art_tasks.task_id", ondelete="CASCADE"), nullable=False, index=True)

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
