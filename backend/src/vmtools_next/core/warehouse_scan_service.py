"""Warehouse scan persistence service.

Persists WarehouseScanner results into SQLite:
  - material_items: aggregated {item_id: count} per warehouse (rebuilt on each scan)
  - container_items: one row per container (primary item + total count)
  - scan_status: progress / counters
  - warehouses.container_count / total_items / last_scan_time

Called by the Socket.IO scan_control flow after a scan finishes/cancels/fails.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from vmtools_next.core.dataclasses import ContainerSnapshot
from vmtools_next.data.models.warehouse import (
    ContainerItemModel,
    MaterialItemModel,
    ScanStatusModel,
    WarehouseModel,
)

logger = logging.getLogger("vmtools.warehouse_scan_service")


def mark_scan_queued(db: Session, warehouse_id: str) -> None:
    """Set scan_status to queued when a scan task enters the queue."""
    st = db.query(ScanStatusModel).filter(
        ScanStatusModel.warehouse_fk == warehouse_id).first()
    if st is None:
        st = ScanStatusModel(warehouse_fk=warehouse_id)
        db.add(st)
    st.status = "queued"
    st.finished_at = None
    db.commit()


def mark_scan_started(db: Session, warehouse_id: str, total_containers: int) -> None:
    """Set scan_status to scanning before starting a scan."""
    from datetime import datetime, timezone
    st = db.query(ScanStatusModel).filter(
        ScanStatusModel.warehouse_fk == warehouse_id).first()
    if st is None:
        st = ScanStatusModel(warehouse_fk=warehouse_id)
        db.add(st)
    st.status = "scanning"
    st.progress = 0.0
    st.total_containers = total_containers
    st.scanned_containers = 0
    st.failed_containers = 0
    st.items_scanned = 0
    st.current_pos = None
    st.started_at = datetime.now(timezone.utc)
    st.finished_at = None
    db.commit()


def update_scan_progress(db: Session, warehouse_id: str,
                         scanned: int, total: int,
                         current_pos: tuple[int, int, int] | None = None,
                         items_scanned: int | None = None) -> None:
    """Update scan_status progress counters (fire-and-forget)."""
    st = db.query(ScanStatusModel).filter(
        ScanStatusModel.warehouse_fk == warehouse_id).first()
    if st is None:
        st = ScanStatusModel(warehouse_fk=warehouse_id)
        db.add(st)
    st.status = "scanning" if scanned < total else st.status
    st.scanned_containers = scanned
    st.total_containers = total
    st.progress = round(scanned / total * 100, 1) if total > 0 else 0.0
    if items_scanned is not None:
        st.items_scanned = items_scanned
    if current_pos is not None:
        st.current_pos = f"{current_pos[0]},{current_pos[1]},{current_pos[2]}"
    db.commit()


def persist_scan_results(db: Session, warehouse_id: str,
                         results: dict[str, ContainerSnapshot],
                         total_containers: int = 0,
                         scanned_containers: int = 0,
                         failed_containers: int = 0,
                         status: str = "finished") -> dict:
    """Write scan results into the warehouse tables.

    Returns a summary dict {warehouse_id, containers, materials, total_items}.
    """
    wh = db.query(WarehouseModel).filter(
        WarehouseModel.warehouse_id == warehouse_id).first()
    if not wh:
        raise ValueError(f"Warehouse not found: {warehouse_id}")

    # 1. Rebuild aggregated material_items (delete → insert, 分批 flush)
    db.query(MaterialItemModel).filter(
        MaterialItemModel.warehouse_fk == warehouse_id).delete()
    db.flush()
    agg: dict[str, tuple[str, int]] = {}  # item_id → (display_name, count)
    for snap in results.values():
        for item in snap.items:
            if not item.item_id:
                continue
            if item.item_id in agg:
                agg[item.item_id] = (agg[item.item_id][0], agg[item.item_id][1] + item.count)
            else:
                agg[item.item_id] = (item.display_name or item.item_id, item.count)
    _FLUSH_EVERY = 500
    _material_rows = 0
    for item_id, (name, count) in agg.items():
        db.add(MaterialItemModel(
            warehouse_fk=warehouse_id,
            item_id=item_id,
            display_name=name,
            count=count,
        ))
        _material_rows += 1
        if _material_rows % _FLUSH_EVERY == 0:
            db.flush()
    db.flush()

    # 2. Rebuild container_items (one row per container: primary item + total, 分批 flush)
    db.query(ContainerItemModel).filter(
        ContainerItemModel.warehouse_fk == warehouse_id).delete()
    db.flush()
    _container_rows = 0
    for snap in results.values():
        primary = snap.items[0] if snap.items else None
        db.add(ContainerItemModel(
            warehouse_fk=warehouse_id,
            container_x=snap.x,
            container_y=snap.y,
            container_z=snap.z,
            item_id=primary.item_id if primary else "",
            item_name_zh=primary.display_name if primary else "",
            count=snap.total_items,
        ))
        _container_rows += 1
        if _container_rows % _FLUSH_EVERY == 0:
            db.flush()
    db.flush()

    # 3. Update warehouse stats
    wh.container_count = len(results)
    wh.total_items = sum(s.total_items for s in results.values())
    wh.last_scan_time = datetime.now(timezone.utc)
    # 4. Update scan_status
    st = db.query(ScanStatusModel).filter(
        ScanStatusModel.warehouse_fk == warehouse_id).first()
    if st is None:
        st = ScanStatusModel(warehouse_fk=warehouse_id)
        db.add(st)
    st.status = status
    st.progress = 100.0 if status == "finished" else st.progress
    st.total_containers = total_containers
    st.scanned_containers = scanned_containers
    st.failed_containers = failed_containers
    st.current_pos = None
    st.items_scanned = sum(s.total_items for s in results.values())
    st.finished_at = datetime.now(timezone.utc)
    db.commit()

    summary = {
        "warehouse_id": warehouse_id,
        "containers": len(results),
        "materials": len(agg),
        "total_items": wh.total_items,
    }
    logger.info("Persisted scan results for %s: %s", warehouse_id, summary)
    return summary