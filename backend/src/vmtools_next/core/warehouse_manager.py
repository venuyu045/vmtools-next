"""Warehouse Manager — CRUD and selection logic for warehouses.

Ported from VMTools-v3 WarehouseManager.java. Manages warehouse
persistence and provides select_best() for material-based selection.
"""
from __future__ import annotations

import logging
import uuid
from typing import Optional

from vmtools_next.core.dataclasses import WarehouseMaterialSnapshot

logger = logging.getLogger("vmtools.warehouse_manager")


class WarehouseManager:
    """Manages warehouse CRUD and selection logic."""

    def __init__(self):
        self._warehouses: dict[str, dict] = {}  # warehouse_id → warehouse data
        self._snapshots: dict[str, WarehouseMaterialSnapshot] = {}  # warehouse_id → snapshot

    def add_warehouse(self, warehouse_id: str, name: str = "",
                       x: int = 0, y: int = 0, z: int = 0,
                       teleport_cmd: str = "") -> dict:
        """Add a new warehouse."""
        warehouse = {
            "id": warehouse_id,
            "name": name or warehouse_id,
            "x": x, "y": y, "z": z,
            "teleport_cmd": teleport_cmd,
            "storage_zones": [],
            "aisle_positions": [],
        }
        self._warehouses[warehouse_id] = warehouse
        logger.info("Added warehouse: %s (%s)", warehouse_id, name)
        return warehouse

    def get_warehouse(self, warehouse_id: str) -> Optional[dict]:
        return self._warehouses.get(warehouse_id)

    def get_all_warehouses(self) -> list[dict]:
        return list(self._warehouses.values())

    def remove_warehouse(self, warehouse_id: str) -> bool:
        if warehouse_id in self._warehouses:
            del self._warehouses[warehouse_id]
            self._snapshots.pop(warehouse_id, None)
            logger.info("Removed warehouse: %s", warehouse_id)
            return True
        return False

    def update_snapshot(self, warehouse_id: str,
                         materials: dict[str, int],
                         container_count: int = 0) -> None:
        """Update the material snapshot for a warehouse."""
        import time
        self._snapshots[warehouse_id] = WarehouseMaterialSnapshot(
            warehouse_id=warehouse_id,
            materials=materials,
            container_count=container_count,
            scanned_at=time.time(),
        )
        logger.info("Updated snapshot for %s: %d materials, %d containers",
                     warehouse_id, len(materials), container_count)

    def get_snapshot(self, warehouse_id: str) -> Optional[WarehouseMaterialSnapshot]:
        return self._snapshots.get(warehouse_id)

    def select_best(self, required_materials: dict[str, int]) -> Optional[str]:
        """Select the best warehouse for the given material requirements.

        Scoring: sum of min(available, required) for each required material.
        Higher score = more materials available = better warehouse.
        """
        best_id = None
        best_score = 0

        for wh_id, snapshot in self._snapshots.items():
            score = 0
            for item_id, needed in required_materials.items():
                available = snapshot.materials.get(item_id, 0)
                score += min(available, needed)
            if score > best_score:
                best_score = score
                best_id = wh_id

        if best_id:
            logger.info("Selected warehouse %s (score=%d, required=%d materials)",
                        best_id, best_score, len(required_materials))
        else:
            logger.warning("No warehouse found for %d required materials", len(required_materials))
        return best_id
