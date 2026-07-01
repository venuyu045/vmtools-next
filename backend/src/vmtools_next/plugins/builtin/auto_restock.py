"""Auto Restock Plugin — automatically triggers restocking when materials are low.

Monitors build tasks and triggers restocking when inventory falls below threshold.
"""
from __future__ import annotations

import logging

from vmtools_next.plugins.base import IPlugin, PluginContext

logger = logging.getLogger("vmtools.plugins.auto_restock")


class Plugin(IPlugin):
    name = "auto_restock"
    version = "1.0.0"

    def __init__(self):
        self._context: PluginContext = None
        self._enabled = True
        self._threshold = 10  # Restock when item count < threshold

    async def load(self, context: PluginContext) -> None:
        self._context = context

    async def start(self) -> None:
        self._enabled = True
        logger.info("Auto-restock plugin started (threshold=%d)", self._threshold)

    async def stop(self) -> None:
        self._enabled = False

    async def reload(self) -> None:
        logger.info("Auto-restock plugin reloaded")

    async def on_event(self, event_type: str, payload: dict) -> None:
        if not self._enabled:
            return
        if event_type == "build.material_low":
            item_id = payload.get("item_id", "")
            count = payload.get("count", 0)
            if count < self._threshold:
                logger.info("Auto-restock triggered: %s (count=%d)", item_id, count)
