"""Plugin management API routes."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from vmtools_next.api.deps import require_admin

router = APIRouter(prefix="/api/plugins", tags=["plugins"])


class PluginBotState(BaseModel):
    bot_id: str
    bot_enabled: bool


class PluginResponse(BaseModel):
    name: str
    version: str
    enabled: bool
    engine: str = "mineflayer"
    description: str = ""
    # 每个 MF bot 对该插件的实际启用状态（2026-08-13，插件管理页展示/配置）
    bots: list[PluginBotState] = []


class ConfigUpdateRequest(BaseModel):
    config: dict


def _pm_or_503():
    from vmtools_next.main import get_plugin_manager
    pm = get_plugin_manager()
    if pm is None:
        raise HTTPException(status_code=503, detail="Plugin manager unavailable")
    return pm


@router.get("", response_model=list[PluginResponse])
def list_plugins(user=Depends(require_admin)):
    """List all plugins (mineflayer engine only), with per-bot enabled states.

    ``bots`` 列出每个 MF bot 对该插件的实际启用状态（bot 记录优先，无记录回退
    全局），供插件管理页展示「哪些 bot 启用了此插件」并在弹窗中直接配置。
    """
    pm = _pm_or_503()
    overview = {p["name"]: p for p in pm.get_plugin_bot_overview()}
    return [
        PluginResponse(
            name=p.name,
            version=p.version,
            enabled=pm.is_enabled(p.name),
            engine=getattr(p, "engine", "mineflayer"),
            description=getattr(p, "description", ""),
            bots=overview.get(p.name, {}).get("bots", []),
        )
        for p in pm.plugins.values()
    ]


@router.get("/status")
def get_bot_plugin_status(bot_id: str, user=Depends(require_admin)):
    """List all plugins with their per-bot enabled state (2026-08-13).

    前端 MF 管理页「插件」tab 数据源：``GET /api/plugins/status?bot_id=xxx``。

    ``enabled`` = 全局启停；``bot_enabled`` = 该 bot 实际生效状态
    （bot 记录优先，无记录回退全局）。
    """
    pm = _pm_or_503()
    return {"bot_id": bot_id, "plugins": pm.get_bot_status(bot_id)}


@router.post("/{name}/enable")
async def enable_plugin(name: str, user=Depends(require_admin), bot_id: str | None = None):
    """Enable a plugin (globally, or for one bot when ``?bot_id=`` is given)."""
    pm = _pm_or_503()
    if name not in pm.plugins:
        raise HTTPException(status_code=404, detail=f"Plugin not found: {name}")
    if bot_id:
        ok = await pm.set_bot_enabled(name, bot_id, True)
        if not ok:
            raise HTTPException(status_code=500, detail=f"Failed to enable plugin for bot: {name}")
        return {"name": name, "bot_id": bot_id, "status": "enabled"}
    ok = await pm.enable(name)
    if not ok:
        raise HTTPException(status_code=500, detail=f"Failed to enable plugin: {name}")
    return {"name": name, "status": "enabled"}


@router.post("/{name}/disable")
async def disable_plugin(name: str, user=Depends(require_admin), bot_id: str | None = None):
    """Disable a plugin (globally, or for one bot when ``?bot_id=`` is given)."""
    pm = _pm_or_503()
    if name not in pm.plugins:
        raise HTTPException(status_code=404, detail=f"Plugin not found: {name}")
    if bot_id:
        ok = await pm.set_bot_enabled(name, bot_id, False)
        if not ok:
            raise HTTPException(status_code=500, detail=f"Failed to disable plugin for bot: {name}")
        return {"name": name, "bot_id": bot_id, "status": "disabled"}
    ok = await pm.disable(name)
    if not ok:
        raise HTTPException(status_code=500, detail=f"Failed to disable plugin: {name}")
    return {"name": name, "status": "disabled"}


@router.post("/{name}/reload")
async def reload_plugin(name: str, user=Depends(require_admin)):
    """Reload a plugin."""
    pm = _pm_or_503()
    if name not in pm.plugins:
        raise HTTPException(status_code=404, detail=f"Plugin not found: {name}")
    ok = await pm.reload(name)
    if not ok:
        raise HTTPException(status_code=500, detail=f"Failed to reload plugin: {name}")
    return {"name": name, "status": "reloaded"}


@router.get("/{name}/config")
def get_plugin_config(name: str, user=Depends(require_admin)):
    """Get a plugin's current config + schema (for the config page / AI editing).

    Returns 404 if the plugin is not loaded.
    """
    pm = _pm_or_503()
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
async def update_plugin_config(name: str, body: ConfigUpdateRequest, user=Depends(require_admin)):
    """Save a plugin config (persisted + hot-applied immediately).

    Example (chat_responder)::

        PUT /api/plugins/chat_responder/config
        {"config": {"commands": {"!ping": "pong! ({username})", "!hi": "你好 {username}"}}}

    Partial updates are merged over the plugin's defaults, so unspecified
    keys keep their current values. Returns the effective (merged) config.
    """
    pm = _pm_or_503()
    if pm.get_config(name) is None:
        raise HTTPException(status_code=404, detail=f"Plugin not found: {name}")
    ok = await pm.set_config(name, body.config)
    if not ok:
        raise HTTPException(status_code=400, detail="Invalid plugin config")
    return {"name": name, "config": pm.get_config(name)}