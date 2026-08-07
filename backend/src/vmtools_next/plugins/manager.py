"""Plugin Manager — manages plugin lifecycle and registry.

Loads plugins from the ``builtin/`` directory. Plugins serve the
mineflayer bot engine only (MCC is a fixed C# client and needs no
plugins). Provides enable/disable/reload functionality.
"""
from __future__ import annotations

import importlib
import logging
import pathlib
from typing import Optional

from vmtools_next.plugins.base import IPlugin, PluginContext

logger = logging.getLogger("vmtools.plugins")

# 插件体系仅服务 mineflayer 引擎；非该引擎的插件一律跳过。
SUPPORTED_ENGINE = "mineflayer"


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
                self._plugins[plugin.name] = plugin
                self._enabled[plugin.name] = True
                logger.info("Loaded builtin plugin: %s v%s (engine=%s)",
                            plugin.name, plugin.version, plugin.engine)
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

    async def dispatch_event(self, event_type: str, payload: dict) -> None:
        """Dispatch an event to all enabled plugins."""
        for name, plugin in self._plugins.items():
            if self._enabled.get(name, False):
                try:
                    await plugin.on_event(event_type, payload)
                except Exception as e:
                    logger.warning("Plugin %s event error: %s", name, e)
