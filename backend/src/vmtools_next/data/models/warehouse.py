"""Warehouse-related ORM models (migrated from vmtools-backend).

Tables: warehouses, material_items, container_items, scan_status, storage_zones
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    Column, String, Integer, BigInteger, Float, DateTime, ForeignKey,
    UniqueConstraint, Text, Boolean, Index,
)
from sqlalchemy.orm import relationship

from vmtools_next.data.db import Base


class WarehouseModel(Base):
    """A registered warehouse (scanned region)."""

    __tablename__ = "warehouses"

    warehouse_id = Column(String, primary_key=True)
    name = Column(String, default="")
    last_scan_time = Column(DateTime, nullable=True)
    container_count = Column(BigInteger, default=0)
    total_items = Column(BigInteger, default=0)
    aisle_lines = Column(Text, default="[]")
    group_id = Column(String, ForeignKey("warehouse_groups.id"), nullable=True, index=True)
    organization_id = Column(String, ForeignKey("organizations.id"), nullable=True, index=True)
    logistics_enabled = Column(Boolean, default=False, nullable=False)
    logistics_teleport_cmd = Column(String, nullable=True)

    materials = relationship("MaterialItemModel", back_populates="warehouse", cascade="all, delete-orphan")
    containers = relationship("ContainerItemModel", back_populates="warehouse", cascade="all, delete-orphan")
    scan_status = relationship("ScanStatusModel", back_populates="warehouse", uselist=False, cascade="all, delete-orphan")
    zones = relationship("StorageZoneModel", back_populates="warehouse", cascade="all, delete-orphan", order_by="StorageZoneModel.created_at")


class MaterialItemModel(Base):
    """Aggregated material totals for a warehouse."""

    __tablename__ = "material_items"

    id = Column(Integer, primary_key=True, autoincrement=True)
    warehouse_fk = Column(String, ForeignKey("warehouses.warehouse_id"), index=True)
    item_id = Column(String, index=True)
    display_name = Column(String)
    count = Column(BigInteger)
    nbt_hash = Column(String, nullable=True)

    __table_args__ = (
        Index("idx_material_items_wh_item", "warehouse_fk", "item_id"),
    )

    warehouse = relationship("WarehouseModel", back_populates="materials")


class ContainerItemModel(Base):
    """Per-container snapshot — one row per container position."""

    __tablename__ = "container_items"

    id = Column(Integer, primary_key=True, autoincrement=True)
    warehouse_fk = Column(String, ForeignKey("warehouses.warehouse_id"), index=True)
    container_x = Column(Integer, nullable=False)
    container_y = Column(Integer, nullable=False)
    container_z = Column(Integer, nullable=False)
    item_id = Column(String, index=True)
    item_name_zh = Column(String)
    count = Column(BigInteger, default=0)

    __table_args__ = (
        UniqueConstraint("warehouse_fk", "container_x", "container_y", "container_z", name="uq_container_pos"),
        Index("idx_container_items_wh_y_z", "warehouse_fk", "container_y", "container_z"),
        Index("idx_container_items_wh_item", "warehouse_fk", "item_id"),
    )

    warehouse = relationship("WarehouseModel", back_populates="containers")


class ScanStatusModel(Base):
    """Live scan progress for a warehouse."""

    __tablename__ = "scan_status"

    warehouse_fk = Column(String, ForeignKey("warehouses.warehouse_id"), primary_key=True)
    status = Column(String, default="idle")  # idle|scanning|paused|finished|cancelled
    progress = Column(Float, default=0.0)
    current_pos = Column(String, nullable=True)
    total_containers = Column(BigInteger, default=0)
    scanned_containers = Column(BigInteger, default=0)
    failed_containers = Column(BigInteger, default=0)

    warehouse = relationship("WarehouseModel", back_populates="scan_status")


class StorageZoneModel(Base):
    """A storage zone within a warehouse, with its own range and aisle lines."""

    __tablename__ = "storage_zones"

    zone_id = Column(String, primary_key=True)
    warehouse_fk = Column(String, ForeignKey("warehouses.warehouse_id"), index=True)
    name = Column(String, default="")
    range_min_x = Column(Integer, default=0)
    range_min_y = Column(Integer, default=0)
    range_min_z = Column(Integer, default=0)
    range_max_x = Column(Integer, default=0)
    range_max_y = Column(Integer, default=0)
    range_max_z = Column(Integer, default=0)
    aisle_lines = Column(Text, default="[]")
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    warehouse = relationship("WarehouseModel", back_populates="zones")
