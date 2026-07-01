"""Discord Notify Plugin — sends notifications to Discord via webhook.

Sends build completion, error, and alert notifications.
"""
from __future__ import annotations

import logging
import httpx

from vmtools_next.plugins.base import IPlugin, PluginContext

logger = logging.getLogger("vmtools.plugins.discord_notify")


class Plugin(IPlugin):
    name = "discord_notify"
    version = "1.0.0"

    def __init__(self):
        self._context: PluginContext = None
        self._webhook_url = ""
        self._enabled = False

    async def load(self, context: PluginContext) -> None:
        self._context = context
        # Read webhook URL from plugin config
        from vmtools_next.config import get_config
        config = get_config()
        discord_config = config.plugins.builtin.discord_notify
        self._webhook_url = discord_config.get("webhook", "")
        self._enabled = discord_config.get("enabled", False) and bool(self._webhook_url)
        logger.debug("Discord notify loaded: enabled=%s, webhook=%s",
                     self._enabled, bool(self._webhook_url))

    async def start(self) -> None:
        if self._enabled:
            logger.info("Discord notify plugin started (webhook configured)")
        else:
            logger.info("Discord notify plugin: disabled or no webhook configured")

    async def stop(self) -> None:
        self._enabled = False

    async def reload(self) -> None:
        logger.info("Discord notify plugin reloaded")

    async def on_event(self, event_type: str, payload: dict) -> None:
        if not self._enabled or not self._webhook_url:
            return

        if event_type in ("build.completed", "build.failed", "alert.triggered"):
            message = self._format_message(event_type, payload)
            await self._send_webhook(message)

    def _format_message(self, event_type: str, payload: dict) -> str:
        if event_type == "build.completed":
            return f"✅ Build completed: {payload.get('name', 'unknown')}"
        elif event_type == "build.failed":
            return f"❌ Build failed: {payload.get('error', 'unknown error')}"
        elif event_type == "alert.triggered":
            return f"⚠️ Alert: {payload.get('message', 'unknown alert')}"
        return f"Event: {event_type}"

    async def _send_webhook(self, content: str) -> None:
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(self._webhook_url, json={"content": content})
                if resp.status_code >= 400:
                    logger.warning("Discord webhook error: %d", resp.status_code)
        except Exception as e:
            logger.warning("Discord webhook failed: %s", e)
