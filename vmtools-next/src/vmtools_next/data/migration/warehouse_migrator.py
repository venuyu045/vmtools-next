"""Warehouse Migrator — converts Java warehouse JSON to SQLite.

Reads DataSerializer output (warehouses.json) and imports to database.
"""
from __future__ import annotations

import json
import logging
import uuid
from typing import Optional

from sqlalchemy.orm import Session

from vmtools_next.data.models.warehouse import WarehouseModel, StorageZoneModel

logger = logging.getLogger("vmtools.migration.warehouse")


class WarehouseMigrator:
    """Migrates Java warehouse JSON to SQLite database."""

    @staticmethod
    def migrate(json_path: str, db: Session, organization_id: Optional[str] = None) -> int:
        """Import warehouses from JSON file.

        Returns number of warehouses imported.
        """
        try:
            with open(json_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            count = 0
            warehouses = data if isinstance(data, list) else data.get("warehouses", [])

            for wh_data in warehouses:
                wh_id = wh_data.get("id", str(uuid.uuid4()))
                existing = db.query(WarehouseModel).filter(WarehouseModel.id == wh_id).first()
                if existing:
                    logger.info("Warehouse %s already exists, skipping", wh_id)
                    continue

                warehouse = WarehouseModel(
                    id=wh_id,
                    name=wh_data.get("name", ""),
                    server_address=wh_data.get("serverAddress", ""),
                    x=wh_data.get("x", 0),
                    y=wh_data.get("y", 0),
                    z=wh_data.get("z", 0),
                    teleport_command=wh_data.get("teleportCmd", ""),
                    organization_id=organization_id,
                )
                db.add(warehouse)

                # Import storage zones
                for zone_data in wh_data.get("storageZones", []):
                    zone = StorageZoneModel(
                        id=str(uuid.uuid4()),
                        warehouse_id=wh_id,
                        name=zone_data.get("name", ""),
                        min_x=zone_data.get("minX", 0),
                        min_y=zone_data.get("minY", 0),
                        min_z=zone_data.get("minZ", 0),
                        max_x=zone_data.get("maxX", 0),
                        max_y=zone_data.get("maxY", 0),
                        max_z=zone_data.get("maxZ", 0),
                    )
                    db.add(zone)

                count += 1

            db.commit()
            logger.info("Imported %d warehouses from %s", count, json_path)
            return count
        except Exception as e:
            db.rollback()
            logger.error("Warehouse migration failed: %s", e)
            return 0
