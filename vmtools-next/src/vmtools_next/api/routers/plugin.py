"""Plugin management API routes."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from vmtools_next.api.deps import get_current_user

router = APIRouter(prefix="/api/plugins", tags=["plugins"])


class PluginResponse(BaseModel):
    name: str
    version: str
    enabled: bool


@router.get("", response_model=list[PluginResponse])
def list_plugins(user=Depends(get_current_user)):
    """List all plugins."""
    try:
        from vmtools_next.main import get_plugin_manager
        pm = get_plugin_manager()
        if pm:
            return [
                PluginResponse(
                    name=p.name,
                    version=p.version,
                    enabled=pm.is_enabled(p.name),
                )
                for p in pm.plugins.values()
            ]
    except Exception:
        pass
    return []


@router.post("/{name}/enable")
async def enable_plugin(name: str, user=Depends(get_current_user)):
    """Enable a plugin."""
    try:
        from vmtools_next.main import get_plugin_manager
        pm = get_plugin_manager()
        if pm:
            success = await pm.enable(name)
            return {"name": name, "status": "enabled" if success else "not_found"}
    except Exception:
        pass
    return {"name": name, "status": "error"}


@router.post("/{name}/disable")
async def disable_plugin(name: str, user=Depends(get_current_user)):
    """Disable a plugin."""
    try:
        from vmtools_next.main import get_plugin_manager
        pm = get_plugin_manager()
        if pm:
            success = await pm.disable(name)
            return {"name": name, "status": "disabled" if success else "not_found"}
    except Exception:
        pass
    return {"name": name, "status": "error"}


@router.post("/{name}/reload")
async def reload_plugin(name: str, user=Depends(get_current_user)):
    """Reload a plugin."""
    try:
        from vmtools_next.main import get_plugin_manager
        pm = get_plugin_manager()
        if pm:
            success = await pm.reload(name)
            return {"name": name, "status": "reloaded" if success else "not_found"}
    except Exception:
        pass
    return {"name": name, "status": "error"}
