"""Data migration API routes."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional

from vmtools_next.api.deps import get_current_user

router = APIRouter(prefix="/api/migration", tags=["migration"])


class MigrationStatus(BaseModel):
    config_migrated: bool = False
    warehouses_migrated: bool = False
    profiles_migrated: bool = False


@router.get("/status", response_model=MigrationStatus)
def get_migration_status(user=Depends(get_current_user)):
    """Get migration status."""
    return MigrationStatus()


@router.post("/config")
def migrate_config(json_path: str, yaml_path: str = "config/config.yaml",
                    user=Depends(get_current_user)):
    """Migrate Java config to YAML."""
    from vmtools_next.data.migration import ConfigMigrator
    success = ConfigMigrator.migrate(json_path, yaml_path)
    if success:
        return {"status": "migrated", "source": json_path, "target": yaml_path}
    raise HTTPException(500, "Migration failed")


@router.post("/warehouses")
def migrate_warehouses(json_path: str, user=Depends(get_current_user)):
    """Migrate Java warehouses to database."""
    from vmtools_next.data.migration import WarehouseMigrator
    from vmtools_next.data.db import get_session_factory
    Session = get_session_factory()
    db = Session()
    try:
        count = WarehouseMigrator.migrate(json_path, db, user.organization_id)
        return {"status": "migrated", "count": count}
    finally:
        db.close()
