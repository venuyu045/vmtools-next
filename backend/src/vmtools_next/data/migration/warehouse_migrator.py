"""Warehouse Migrator — converts Java warehouse JSON to SQLite.

Reads DataSerializer output (warehouses.json) and imports to database.
Field names are aligned with the current ORM models (WarehouseModel /
StorageZoneModel).
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
                wh_id = wh_data.get("id", wh_data.get("warehouseId", str(uuid.uuid4())))
                existing = db.query(WarehouseModel).filter(WarehouseModel.warehouse_id == wh_id).first()
                if existing:
                    logger.info("Warehouse %s already exists, skipping", wh_id)
                    continue

                warehouse = WarehouseModel(
                    warehouse_id=wh_id,
                    name=wh_data.get("name", wh_data.get("displayName", "")),
                    aisle_lines=json.dumps(
                        wh_data.get("aisleLines", wh_data.get("aisle_lines", [])),
                        ensure_ascii=False,
                    ),
                    organization_id=organization_id or wh_data.get("organizationId"),
                    logistics_teleport_cmd=wh_data.get("teleportCmd") or wh_data.get("teleport_command"),
                )
                db.add(warehouse)

                # Import storage zones
                for zone_data in wh_data.get("storageZones", wh_data.get("zones", [])):
                    zone = StorageZoneModel(
                        zone_id=zone_data.get("id", zone_data.get("zoneId", str(uuid.uuid4()))),
                        warehouse_fk=wh_id,
                        name=zone_data.get("name", ""),
                        range_min_x=zone_data.get("minX", zone_data.get("rangeMinX", 0)),
                        range_min_y=zone_data.get("minY", zone_data.get("rangeMinY", 0)),
                        range_min_z=zone_data.get("minZ", zone_data.get("rangeMinZ", 0)),
                        range_max_x=zone_data.get("maxX", zone_data.get("rangeMaxX", 0)),
                        range_max_y=zone_data.get("maxY", zone_data.get("rangeMaxY", 0)),
                        range_max_z=zone_data.get("maxZ", zone_data.get("rangeMaxZ", 0)),
                        aisle_lines=json.dumps(
                            zone_data.get("aisleLines", zone_data.get("aisle_lines", [])),
                            ensure_ascii=False,
                        ),
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