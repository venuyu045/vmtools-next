"""MCC Session Pool — manages multiple MccMcpClient instances.

One MccMcpClient per bot_id. Provides:
  - connect_bot / disconnect_bot: manage individual bot connections
  - get_client: get the MccMcpClient for a bot_id
  - health_check_loop: periodic heartbeat via get_session_status()
  - event_poll_loop: poll get_recent_events() every 500ms and dispatch

Ported from vmtools-backend/mcc_connection_manager.py with MCP protocol.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Awaitable, Callable, Optional

from vmtools_next.adapters.mcc.mcc_mcp_client import MccMcpClient, MccMcpError

logger = logging.getLogger("vmtools.mcc_pool")

# Type alias for event handlers
EventHandler = Callable[[str, dict], Awaitable[None]]


class MccEventDispatcher:
    """Dispatches MCC events to registered async handlers."""

    def __init__(self):
        self._handlers: dict[str, list[EventHandler]] = {}

    def register(self, event: str, handler: EventHandler) -> None:
        if event not in self._handlers:
            self._handlers[event] = []
        if handler not in self._handlers[event]:
            self._handlers[event].append(handler)

    def unregister(self, event: str, handler: EventHandler) -> None:
        handlers = self._handlers.get(event)
        if handlers and handler in handlers:
            handlers.remove(handler)

    async def dispatch(self, event: str, bot_id: str, data: dict) -> None:
        handlers = list(self._handlers.get(event, []))
        wildcard = list(self._handlers.get("*", []))
        for handler in handlers + wildcard:
            try:
                await handler(bot_id, data)
            except Exception as e:
                logger.error("Event handler error (%s, bot=%s): %s", event, bot_id, e)


class MccSessionPool:
    """Manages a pool of MCC MCP client sessions.

    One MccMcpClient per bot_id. Provides health checking and event polling.
    """

    def __init__(self, health_check_interval: float = 5.0,
                 event_poll_interval: float = 0.5):
        self._clients: dict[str, MccMcpClient] = {}
        self._bot_status: dict[str, dict] = {}  # bot_id → status dict
        self._last_event_ids: dict[str, int] = {}  # bot_id → last event id
        self._dispatcher = MccEventDispatcher()
        self._health_check_interval = health_check_interval
        self._event_poll_interval = event_poll_interval
        self._running = False
        self._health_task: Optional[asyncio.Task] = None
        self._event_task: Optional[asyncio.Task] = None
        self._consecutive_failures: dict[str, int] = {}

    @property
    def dispatcher(self) -> MccEventDispatcher:
        return self._dispatcher

    def get_client(self, bot_id: str) -> Optional[MccMcpClient]:
        return self._clients.get(bot_id)

    def get_all_clients(self) -> dict[str, MccMcpClient]:
        return dict(self._clients)

    def get_bot_status(self, bot_id: str) -> dict:
        return self._bot_status.get(bot_id, {"status": "offline"})

    async def connect_bot(self, bot_id: str, host: str = "127.0.0.1",
                           port: int = 33333, auth_token: Optional[str] = None,
                           auth_token_env: Optional[str] = None) -> bool:
        """Connect a new bot or reconnect an existing one.

        Args:
            bot_id: Unique bot identifier
            host: MCC MCP server host
            port: MCC MCP server port
            auth_token: Explicit auth token (takes priority)
            auth_token_env: Environment variable name to read auth token from
        """
        # Read auth token from environment if not explicitly provided
        if not auth_token and auth_token_env:
            import os
            auth_token = os.environ.get(auth_token_env)
            if auth_token:
                logger.debug("Loaded auth token from env var %s", auth_token_env)

        if bot_id in self._clients:
            await self.disconnect_bot(bot_id)

        client = MccMcpClient(host=host, port=port, auth_token=auth_token)
        connected = await client.connect()

        self._clients[bot_id] = client
        self._bot_status[bot_id] = {
            "status": "online" if connected else "error",
            "host": host,
            "port": port,
            "connected_at": datetime.now(timezone.utc).isoformat() if connected else None,
            "last_heartbeat": datetime.now(timezone.utc).isoformat() if connected else None,
        }
        self._consecutive_failures[bot_id] = 0

        if connected:
            logger.info("Bot %s connected to MCP at %s:%d", bot_id, host, port)
        else:
            logger.warning("Bot %s failed to connect to MCP at %s:%d", bot_id, host, port)

        return connected

    async def disconnect_bot(self, bot_id: str) -> None:
        """Disconnect and remove a bot."""
        client = self._clients.pop(bot_id, None)
        if client:
            await client.disconnect()
        self._bot_status.pop(bot_id, None)
        self._last_event_ids.pop(bot_id, None)
        self._consecutive_failures.pop(bot_id, None)
        logger.info("Bot %s disconnected", bot_id)

    async def start(self) -> None:
        """Start background health check and event polling loops."""
        if self._running:
            return
        self._running = True
        self._health_task = asyncio.create_task(self._health_check_loop())
        self._event_task = asyncio.create_task(self._event_poll_loop())
        logger.info("MccSessionPool started (health=%ds, events=%dms)",
                     self._health_check_interval, self._event_poll_interval * 1000)

    async def stop(self) -> None:
        """Stop background loops and disconnect all bots."""
        self._running = False
        if self._health_task:
            self._health_task.cancel()
        if self._event_task:
            self._event_task.cancel()
        for bot_id in list(self._clients.keys()):
            await self.disconnect_bot(bot_id)
        logger.info("MccSessionPool stopped")

    async def _health_check_loop(self) -> None:
        """Periodically check each bot's health via get_session_status()."""
        while self._running:
            try:
                for bot_id, client in list(self._clients.items()):
                    if not client.is_connected:
                        continue
                    try:
                        status = await client.get_session_status()
                        self._bot_status[bot_id]["status"] = "online"
                        self._bot_status[bot_id]["last_heartbeat"] = datetime.now(timezone.utc).isoformat()
                        self._consecutive_failures[bot_id] = 0
                    except MccMcpError as e:
                        self._consecutive_failures[bot_id] = self._consecutive_failures.get(bot_id, 0) + 1
                        if self._consecutive_failures[bot_id] >= 3:
                            self._bot_status[bot_id]["status"] = "error"
                            logger.warning("Bot %s health check failed 3x: %s", bot_id, e)
            except Exception as e:
                logger.error("Health check loop error: %s", e)
            await asyncio.sleep(self._health_check_interval)

    async def _event_poll_loop(self) -> None:
        """Poll get_recent_events() for each bot and dispatch."""
        while self._running:
            try:
                for bot_id, client in list(self._clients.items()):
                    if not client.is_connected:
                        continue
                    try:
                        last_id = self._last_event_ids.get(bot_id, 0)
                        result = await client.get_recent_events(after_id=last_id, max_count=50)
                        events = result.get("events", [])
                        for event in events:
                            event_id = event.get("id", 0)
                            event_type = event.get("type", "unknown")
                            if event_id > last_id:
                                self._last_event_ids[bot_id] = event_id
                            await self._dispatcher.dispatch(event_type, bot_id, event)
                    except MccMcpError:
                        pass  # Silently skip polling errors
            except Exception as e:
                logger.error("Event poll loop error: %s", e)
            await asyncio.sleep(self._event_poll_interval)
