"""Configuration management API routes."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from typing import Optional, Any

from vmtools_next.api.deps import get_current_user
from vmtools_next.config import get_config, reload_config, save_mcc_config

router = APIRouter(prefix="/api/config", tags=["config"])


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
def update_mcc_config(data: MccConfigUpdate, user=Depends(get_current_user)):
    """Update MCC section in config.yaml."""
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
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/reload")
def reload(user=Depends(get_current_user)):
    """Reload configuration from files."""
    try:
        new_config = reload_config()
        return {"status": "reloaded", "config": new_config.model_dump()}
    except Exception as e:
        return {"status": "error", "error": str(e)}
