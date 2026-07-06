"""Configuration management API routes."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from typing import Optional, Any

from vmtools_next.api.deps import get_current_user
from vmtools_next.config import get_config, reload_config, save_mcc_config
from vmtools_next.infra.logging import get_logger

logger = get_logger("api.config")
router = APIRouter(prefix="/api/config", tags=["config"])


def _require_site_admin(user=Depends(get_current_user)):
    """Dependency that requires site_admin role for config mutations."""
    if user.role != "site_admin":
        raise HTTPException(status_code=403, detail="Only site admin can modify configuration")
    return user


class MccConfigUpdate(BaseModel):
    instance_root: Optional[str] = None
    binary_path: Optional[str] = None
    launch_command: Optional[list[str]] = None
    instance_start_port: Optional[int] = Field(default=None, ge=1024, le=65535)
    instance_end_port: Optional[int] = Field(default=None, ge=1024, le=65535)
    max_instances: Optional[int] = Field(default=None, ge=1, le=100)
    log_retention_days: Optional[int] = Field(default=None, ge=1, le=365)


@router.get("")
def get_current_config(user=Depends(get_current_user)):
    """Get the current configuration."""
    config = get_config()
    return config.model_dump()


@router.get("/mcc")
def get_mcc_config(user=Depends(get_current_user)):
    """Get MCC section of the configuration."""
    config = get_config()
    return config.mcc.model_dump()


@router.put("/mcc")
def update_mcc_config(data: MccConfigUpdate, user=Depends(_require_site_admin)):
    """Update MCC section in config.yaml. Requires site_admin."""
    try:
        config = save_mcc_config(
            instance_root=data.instance_root,
            binary_path=data.binary_path,
            launch_command=data.launch_command,
            instance_start_port=data.instance_start_port,
            instance_end_port=data.instance_end_port,
            max_instances=data.max_instances,
            log_retention_days=data.log_retention_days,
        )
        return {"status": "saved", "mcc": config.mcc.model_dump()}
    except Exception as e:
        logger.error("Failed to update MCC config: %s", e)
        raise HTTPException(status_code=500, detail="Failed to save configuration")


@router.post("/reload")
def reload(user=Depends(_require_site_admin)):
    """Reload configuration from files. Requires site_admin."""
    try:
        new_config = reload_config()
        return {"status": "reloaded", "config": new_config.model_dump()}
    except Exception as e:
        logger.error("Failed to reload config: %s", e)
        raise HTTPException(status_code=500, detail="Failed to reload configuration")
