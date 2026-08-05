"""Mineflayer MiniHud Adapter — Servux 容器预览（不打开容器）。

Implements AbstractMiniHudAdapter using the Servux Entity Data Sync protocol
(via MineflayerBridgeClient → node bot's servux handler).

Unlike the old open→read→close flow, this adapter requests the BlockEntity NBT
directly by position — the container is NEVER opened in-game. If the server
does not have Servux (handshake fails), reads fail with a clear error.
"""

from __future__ import annotations

import logging
from typing import Optional

from vmtools_next.adapters.abstract.minihud import (
    AbstractMiniHudAdapter,
    ReadResult,
)
from vmtools_next.adapters.mineflayer.mineflayer_client import (
    MineflayerBridgeClient,
    MineflayerError,
)
from vmtools_next.core.dataclasses import MaterialStack

logger = logging.getLogger("vmtools.mf_minihud")


class MfMiniHudAdapter(AbstractMiniHudAdapter):
    """Servux container preview via mineflayer WebSocket bridge."""

    def __init__(self, client: MineflayerBridgeClient):
        self._client = client

    def is_available(self) -> bool:
        return self._client.is_connected

    async def ensure_servux(self, timeout_ms: int = 4000) -> bool:
        """Ensure the bot has successfully handshaken with the server's Servux plugin."""
        try:
            result = await self._client.servux_handshake(timeout_ms=timeout_ms)
            return bool(result.get("success"))
        except Exception as e:
            logger.warning("Servux handshake failed: %s", e)
            return False

    async def read_container_items(self, x: int, y: int, z: int,
                                    timeout_ms: int = 5000) -> ReadResult:
        """Read container contents via Servux preview — never opens the container.

        Returns ReadResult with items on success, or ReadResult.failed() on error
        (e.g. Servux not available on the server).
        """
        if not self._client.is_connected:
            return ReadResult.failed("Not connected to mineflayer bot")

        try:
            result = await self._client.preview_container_at(x, y, z, timeout_ms=timeout_ms)
            if not result.get("success"):
                return ReadResult.failed(result.get("error", "Servux read failed"))

            items_raw = result.get("items", [])
            items = [
                MaterialStack(
                    item_id=item.get("item_id", item.get("name", item.get("type", ""))),
                    display_name=item.get("display_name", ""),
                    count=item.get("count", 0),
                    slot=item.get("slot", -1),
                )
                for item in items_raw
            ]
            return ReadResult.ok(items, source="servux")

        except MineflayerError as e:
            return ReadResult.failed(str(e))
        except Exception as e:
            logger.error("read_container_items error at (%d,%d,%d): %s", x, y, z, e)
            return ReadResult.failed(str(e))

    async def prefetch_container(self, x: int, y: int, z: int) -> None:
        """No-op: Servux reads are direct requests, no pre-fetch concept."""
        pass
