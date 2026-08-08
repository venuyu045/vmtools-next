"""Plugin Manager — manages plugin lifecycle and registry.

Loads plugins from the ``builtin/`` directory. Plugins serve the
mineflayer bot engine only (MCC is a fixed C# client and needs no
plugins). Provides enable/disable/reload functionality plus
per-plugin config persistence (``plugin_states`` table).
"""
from __future__ import annotations

import importlib
import json
import pathlib
from datetime import datetime, timezone
from typing import Optional

from vmtools_next.infra.logging import get_logger
from vmtools_next.plugins.base import IPlugin, PluginContext

logger = get_logger("plugins")

# 插件体系仅服务 mineflayer 引擎；非该引擎的插件一律跳过。
SUPPORTED_ENGINE = "mineflayer"


def _deep_merge(base: dict, overlay: dict) -> dict:
    """Recursively merge overlay into base (overlay wins)."""
    result = dict(base)
    for key, val in overlay.items():
        if key in result and isinstance(result[key], dict) and isinstance(val, dict):
            result[key] = _deep_merge(result[key], val)
        else:
            result[key] = val
    return result


def _persist_plugin_state(name: str, version: str, enabled: bool, config: Optional[dict]) -> None:
    """Upsert plugin state (enabled + config JSON) into the plugin_states table."""
    try:
        from vmtools_next.data.db import get_session_factory
        from vmtools_next.data.models.plugin import PluginStateModel
        db = get_session_factory()()
        try:
            row = db.query(PluginStateModel).filter(PluginStateModel.name == name).first()
            if row is None:
                row = PluginStateModel(name=name, version=version, enabled=enabled,
                                       config=json.dumps(config, ensure_ascii=False) if config is not None else None)
                db.add(row)
            else:
                row.version = version
                row.enabled = enabled
                row.config = json.dumps(config, ensure_ascii=False) if config is not None else row.config
                row.last_reload_at = datetime.now(timezone.utc)
            db.commit()
        finally:
            db.close()
    except Exception as e:
        logger.warning("Failed to persist plugin state %s: %s", name, e)


def _load_persisted_config(name: str) -> Optional[dict]:
    """Read persisted config JSON for a plugin; None if never saved."""
    try:
        from vmtools_next.data.db import get_session_factory
        from vmtools_next.data.models.plugin import PluginStateModel
        db = get_session_factory()()
        try:
            row = db.query(PluginStateModel).filter(PluginStateModel.name == name).first()
            if row is None or not row.config:
                return None
            parsed = json.loads(row.config)
            return parsed if isinstance(parsed, dict) else None
        finally:
            db.close()
    except Exception as e:
        logger.warning("Failed to load plugin config %s: %s", name, e)
        return None


def _load_persisted_enabled(name: str) -> Optional[bool]:
    """Read persisted enabled flag; None if never saved (default enabled)."""
    try:
        from vmtools_next.data.db import get_session_factory
        from vmtools_next.data.models.plugin import PluginStateModel
        db = get_session_factory()()
        try:
            row = db.query(PluginStateModel).filter(PluginStateModel.name == name).first()
            if row is None:
                return None
            return bool(row.enabled)
        finally:
            db.close()
    except Exception as e:
        logger.warning("Failed to load plugin enabled %s: %s", name, e)
        return None


class PluginManager:
    """Manages plugin lifecycle."""

    def __init__(self, context: PluginContext):
        self._context = context
        self._plugins: dict[str, IPlugin] = {}
        self._enabled: dict[str, bool] = {}

    @property
    def plugins(self) -> dict[str, IPlugin]:
        return dict(self._plugins)

    async def load_builtin(self) -> None:
        """Load all builtin plugins (mineflayer engine only).

        Dynamically discovers every ``*.py`` module in the ``builtin/``
        directory, so adding a new MF plugin is just adding a file.
        """
        builtin_dir = pathlib.Path(__file__).resolve().parent / "builtin"
        for module_path in sorted(builtin_dir.glob("*.py")):
            if module_path.name.startswith("_"):
                continue
            module_name = f"vmtools_next.plugins.builtin.{module_path.stem}"
            try:
                module = importlib.import_module(module_name)
                if not hasattr(module, "Plugin"):
                    continue
                plugin_cls = module.Plugin
                plugin = plugin_cls()
                if getattr(plugin, "engine", "mineflayer") != SUPPORTED_ENGINE:
                    logger.info("Skip plugin %s: engine=%s (only %s supported)",
                                getattr(plugin, "name", module_path.stem),
                                getattr(plugin, "engine", "?"), SUPPORTED_ENGINE)
                    continue
                await plugin.load(self._context)
                # 配置注入：默认配置 + 持久化配置深合并 → apply_config
                merged = _deep_merge(
                    dict(getattr(plugin, "default_config", {}) or {}),
                    _load_persisted_config(plugin.name) or {},
                )
                try:
                    plugin.apply_config(merged)
                except Exception as e:
                    logger.warning("Plugin %s apply_config failed: %s", plugin.name, e)
                # 启用状态持久化：DB 中已禁用则保持禁用（重启不自动恢复启用）
                persisted_enabled = _load_persisted_enabled(plugin.name)
                enabled = persisted_enabled if persisted_enabled is not None else True
                _persist_plugin_state(plugin.name, plugin.version, enabled, merged)
                self._plugins[plugin.name] = plugin
                self._enabled[plugin.name] = enabled
                logger.info("Loaded builtin plugin: %s v%s (engine=%s, enabled=%s)",
                            plugin.name, plugin.version, plugin.engine, enabled)
            except Exception as e:
                logger.warning("Failed to load builtin plugin %s: %s", module_path.name, e)

    async def start_all(self) -> None:
        """Start all enabled plugins."""
        for name, plugin in self._plugins.items():
            if self._enabled.get(name, False):
                try:
                    await plugin.start()
                    logger.info("Started plugin: %s", name)
                except Exception as e:
                    logger.error("Failed to start plugin %s: %s", name, e)

    async def stop_all(self) -> None:
        """Stop all plugins."""
        for name, plugin in self._plugins.items():
            try:
                await plugin.stop()
            except Exception as e:
                logger.warning("Error stopping plugin %s: %s", name, e)

    async def enable(self, name: str) -> bool:
        """Enable a plugin."""
        if name not in self._plugins:
            logger.warning("Plugin not found: %s", name)
            return False
        self._enabled[name] = True
        try:
            await self._plugins[name].start()
            _persist_plugin_state(name, self._plugins[name].version, True, None)
            logger.info("Enabled plugin: %s", name)
            return True
        except Exception as e:
            logger.error("Failed to enable plugin %s: %s", name, e)
            return False

    async def disable(self, name: str) -> bool:
        """Disable a plugin."""
        if name not in self._plugins:
            return False
        self._enabled[name] = False
        try:
            await self._plugins[name].stop()
            _persist_plugin_state(name, self._plugins[name].version, False, None)
            logger.info("Disabled plugin: %s", name)
            return True
        except Exception as e:
            logger.error("Failed to disable plugin %s: %s", name, e)
            return False

    async def reload(self, name: str) -> bool:
        """Reload a plugin."""
        if name not in self._plugins:
            return False
        try:
            await self._plugins[name].reload()
            logger.info("Reloaded plugin: %s", name)
            return True
        except Exception as e:
            logger.error("Failed to reload plugin %s: %s", name, e)
            return False

    async def reload_all(self) -> None:
        """Reload all plugins."""
        for name in list(self._plugins.keys()):
            try:
                await self._plugins[name].reload()
                logger.info("Reloaded plugin: %s", name)
            except Exception as e:
                logger.error("Failed to reload plugin %s: %s", name, e)

    def is_enabled(self, name: str) -> bool:
        return self._enabled.get(name, False)

    def get_config(self, name: str) -> Optional[dict]:
        """Return the plugin's current (merged) config dict."""
        plugin = self._plugins.get(name)
        if plugin is None:
            return None
        # 优先返回持久化配置（保持与插件实际生效值一致）
        persisted = _load_persisted_config(name)
        if persisted is not None:
            return persisted
        default = dict(getattr(plugin, "default_config", {}) or {})
        return default or {}

    def get_config_schema(self, name: str) -> dict:
        """Return the plugin's config schema (for UI rendering / validation)."""
        plugin = self._plugins.get(name)
        if plugin is None:
            return {}
        return dict(getattr(plugin, "config_schema", {}) or {})

    async def set_config(self, name: str, config: dict) -> bool:
        """Validate & persist a plugin config, then hot-apply it.

        The incoming config is merged over the plugin's defaults so a
        partial update keeps unspecified keys intact. Returns True on success.
        """
        plugin = self._plugins.get(name)
        if plugin is None:
            return False
        if not isinstance(config, dict):
            return False
        merged = _deep_merge(
            dict(getattr(plugin, "default_config", {}) or {}),
            config,
        )
        try:
            plugin.apply_config(merged)
        except Exception as e:
            logger.error("Plugin %s apply_config failed: %s", name, e)
            return False
        _persist_plugin_state(name, plugin.version, self._enabled.get(name, True), merged)
        logger.info("Plugin %s config updated: %s", name, merged)
        return True

    async def dispatch_event(self, event_type: str, payload: dict) -> None:
        """Dispatch an event to all enabled plugins."""
        for name, plugin in self._plugins.items():
            if self._enabled.get(name, False):
                try:
                    await plugin.on_event(event_type, payload)
                except Exception as e:
                    logger.warning("Plugin %s event error: %s", name, e)
