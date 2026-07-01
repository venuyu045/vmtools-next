"""Configuration management API routes."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from typing import Optional, Any

from vmtools_next.api.deps import get_current_user
from vmtools_next.config import get_config, reload_config

router = APIRouter(prefix="/api/config", tags=["config"])


@router.get("")
def get_current_config(user=Depends(get_current_user)):
    """Get the current configuration."""
    config = get_config()
    return config.model_dump()


@router.post("/reload")
def reload(user=Depends(get_current_user)):
    """Reload configuration from files."""
    try:
        new_config = reload_config()
        return {"status": "reloaded", "config": new_config.model_dump()}
    except Exception as e:
        return {"status": "error", "error": str(e)}
