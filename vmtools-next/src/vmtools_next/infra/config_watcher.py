"""Config Watcher — monitors YAML config files for changes using watchdog.

Triggers pydantic-settings reload when config files change.
"""
from __future__ import annotations

import asyncio
import logging
import pathlib
from typing import Callable, Optional, Awaitable

logger = logging.getLogger("vmtools.config_watcher")

try:
    from watchdog.observers import Observer
    from watchdog.events import FileSystemEventHandler, FileModifiedEvent
    HAS_WATCHDOG = True
except ImportError:
    HAS_WATCHDOG = False
    logger.warning("watchdog not installed, config hot-reload disabled")


class ConfigChangeHandler(FileSystemEventHandler if HAS_WATCHDOG else object):
    """Handles file system events for config files."""

    def __init__(self, callback: Callable[[], Awaitable[None]]):
        self._callback = callback
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    def set_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    def on_modified(self, event):
        if not event.is_directory and event.src_path.endswith(('.yaml', '.yml')):
            logger.info("Config file changed: %s", event.src_path)
            if self._loop and self._callback:
                asyncio.run_coroutine_threadsafe(self._callback(), self._loop)


class ConfigWatcher:
    """Watches config directory for changes."""

    def __init__(self, config_dir: str, on_change: Callable[[], Awaitable[None]]):
        self._config_dir = pathlib.Path(config_dir)
        self._on_change = on_change
        self._observer: Optional[Observer] = None

    async def start(self) -> None:
        if not HAS_WATCHDOG:
            logger.warning("Config watcher not available (watchdog not installed)")
            return

        if not self._config_dir.is_dir():
            logger.warning("Config directory not found: %s", self._config_dir)
            return

        handler = ConfigChangeHandler(self._on_change)
        handler.set_loop(asyncio.get_event_loop())

        self._observer = Observer()
        self._observer.schedule(handler, str(self._config_dir), recursive=False)
        self._observer.daemon = True
        self._observer.start()
        logger.info("Config watcher started: %s", self._config_dir)

    async def stop(self) -> None:
        if self._observer:
            self._observer.stop()
            self._observer.join(timeout=5)
            logger.info("Config watcher stopped")
