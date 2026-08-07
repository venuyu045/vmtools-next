"""Plugin management API routes."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from vmtools_next.api.deps import get_current_user

router = APIRouter(prefix="/api/plugins", tags=["plugins"])


class PluginResponse(BaseModel):
    name: str
    version: str
    enabled: bool
    engine: str = "mineflayer"
    description: str = ""


class ConfigUpdateRequest(BaseModel):
    config: dict


@router.get("", response_model=list[PluginResponse])
def list_plugins(user=Depends(get_current_user)):
    """List all plugins (mineflayer engine only)."""
    try:
        from vmtools_next.main import get_plugin_manager
        pm = get_plugin_manager()
        if pm:
            return [
                PluginResponse(
                    name=p.name,
                    version=p.version,
                    enabled=pm.is_enabled(p.name),
                    engine=getattr(p, "engine", "mineflayer"),
                    description=getattr(p, "description", ""),
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


@router.get("/{name}/config")
def get_plugin_config(name: str, user=Depends(get_current_user)):
    """Get a plugin's current config + schema (for the config page / AI editing).

    Returns 404 if the plugin is not loaded.
    """
    from vmtools_next.main import get_plugin_manager
    pm = get_plugin_manager()
    if pm is None:
        raise HTTPException(status_code=404, detail="Plugin manager unavailable")
    config = pm.get_config(name)
    if config is None:
        raise HTTPException(status_code=404, detail=f"Plugin not found: {name}")
    return {
        "name": name,
        "enabled": pm.is_enabled(name),
        "config": config,
        "schema": pm.get_config_schema(name),
        "default_config": dict(getattr(pm.plugins.get(name), "default_config", {}) or {}),
    }


@router.put("/{name}/config")
async def update_plugin_config(name: str, body: ConfigUpdateRequest, user=Depends(get_current_user)):
    """Save a plugin config (persisted + hot-applied immediately).

    Example (chat_responder)::

        PUT /api/plugins/chat_responder/config
        {"config": {"commands": {"!ping": "pong! ({username})", "!hi": "你好 {username}"}}}

    Partial updates are merged over the plugin's defaults, so unspecified
    keys keep their current values. Returns the effective (merged) config.
    """
    from vmtools_next.main import get_plugin_manager
    pm = get_plugin_manager()
    if pm is None:
        raise HTTPException(status_code=500, detail="Plugin manager unavailable")
    if pm.get_config(name) is None:
        raise HTTPException(status_code=404, detail=f"Plugin not found: {name}")
    ok = await pm.set_config(name, body.config)
    if not ok:
        raise HTTPException(status_code=400, detail="Invalid plugin config")
    return {"name": name, "config": pm.get_config(name)}
