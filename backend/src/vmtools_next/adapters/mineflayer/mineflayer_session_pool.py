"""Session pool for mineflayer bot WebSocket connections.

Manages MineflayerBridgeClient instances per bot, with health checks.
Unlike MccSessionPool, no event polling is needed — mineflayer pushes
events via WebSocket automatically.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

from .mineflayer_client import MineflayerBridgeClient

logger = logging.getLogger("vmtools.mineflayer_session_pool")


class MineflayerSessionPool:
    """Manages mineflayer bot WebSocket connections.

    One MineflayerBridgeClient per bot. Health checks via WS ping/pong
    (handled by the websockets library automatically).
    """

    def __init__(self, health_check_interval: float = 5.0):
        self._clients: dict[str, MineflayerBridgeClient] = {}
        self._health_check_interval = health_check_interval
        self._health_check_task: Optional[asyncio.Task] = None
        self._running = False

    @property
    def running(self) -> bool:
        return self._running

    def get_client(self, bot_id: str) -> Optional[MineflayerBridgeClient]:
        """Get the bridge client for a bot."""
        return self._clients.get(bot_id)

    def is_connected(self, bot_id: str) -> bool:
        client = self._clients.get(bot_id)
        return client is not None and client.is_connected

    async def connect_bot(self, bot_id: str, host: str = "127.0.0.1",
                           port: int = 44444) -> bool:
        """Connect to a mineflayer bot process."""
        # 如果已有连接，先断开
        existing = self._clients.get(bot_id)
        if existing:
            await existing.disconnect()

        client = MineflayerBridgeClient(host=host, port=port)
        ok = await client.connect()
        if ok:
            self._clients[bot_id] = client
            logger.info("Bot %s connected at %s:%d", bot_id, host, port)
        else:
            logger.warning("Bot %s failed to connect at %s:%d", bot_id, host, port)
        return ok

    async def disconnect_bot(self, bot_id: str) -> None:
        """Disconnect a bot."""
        client = self._clients.pop(bot_id, None)
        if client:
            await client.disconnect()
            logger.info("Bot %s disconnected", bot_id)

    async def disconnect_all(self) -> None:
        """Disconnect all bots."""
        for bot_id in list(self._clients.keys()):
            await self.disconnect_bot(bot_id)

    async def start(self) -> None:
        """Start health check loop."""
        self._running = True
        self._health_check_task = asyncio.create_task(self._health_check_loop())
        logger.info("MineflayerSessionPool started (health check every %ss)",
                     self._health_check_interval)

    async def stop(self) -> None:
        """Stop health check loop and disconnect all bots."""
        self._running = False
        if self._health_check_task:
            self._health_check_task.cancel()
            try:
                await self._health_check_task
            except asyncio.CancelledError:
                pass
            self._health_check_task = None
        await self.disconnect_all()
        logger.info("MineflayerSessionPool stopped")

    async def _health_check_loop(self) -> None:
        """Periodic health check — WS library handles pings internally."""
        while self._running:
            try:
                await asyncio.sleep(self._health_check_interval)
                for bot_id, client in list(self._clients.items()):
                    if not client.is_connected:
                        logger.warning("Bot %s disconnected during health check", bot_id)
                        # 不做自动重连，由 MineflayerProcessManager 处理
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Health check error: %s", e)
