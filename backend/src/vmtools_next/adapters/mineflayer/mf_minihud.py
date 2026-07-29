"""Mineflayer MiniHud Adapter — container reading via WebSocket.

Implements AbstractMiniHudAdapter using MineflayerBridgeClient.
Follows the same open→read→close three-step protocol as the MCC version,
but uses container_id (UUID string) instead of MCC's integer inventory_id.
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
    """Container reading via mineflayer WebSocket bridge."""

    def __init__(self, client: MineflayerBridgeClient):
        self._client = client

    def is_available(self) -> bool:
        return self._client.is_connected

    async def read_container_items(self, x: int, y: int, z: int,
                                    timeout_ms: int = 5000) -> ReadResult:
        """Open container, read contents, close container.

        Returns ReadResult with items on success, or ReadResult.failed() on error.
        """
        if not self._client.is_connected:
            return ReadResult.failed("Not connected to mineflayer bot")

        container_id: Optional[str] = None
        try:
            # 1. 打开容器
            open_result = await self._client.open_container_at(x, y, z, timeout_ms=timeout_ms)
            if not open_result.get("success"):
                return ReadResult.failed(open_result.get("error", "Failed to open container"))

            container_id = open_result.get("container_id")
            if not container_id:
                return ReadResult.failed("No container_id in response")

            # 2. 读取容器快照
            snapshot = await self._client.get_container_snapshot(container_id)
            items_raw = snapshot.get("items", [])

            # 3. 转换为 MaterialStack
            items = [
                MaterialStack(
                    item_id=item.get("name", item.get("type", "")),
                    display_name=item.get("display_name", ""),
                    count=item.get("count", 0),
                    slot=item.get("slot", -1),
                )
                for item in items_raw
            ]

            return ReadResult.ok(items, source="mineflayer_ws")

        except MineflayerError as e:
            return ReadResult.failed(str(e))
        except Exception as e:
            logger.error("read_container_items error at (%d,%d,%d): %s", x, y, z, e)
            return ReadResult.failed(str(e))
        finally:
            # 确保关闭容器
            if container_id:
                try:
                    await self._client.close_container(container_id, timeout_ms=timeout_ms)
                except Exception as e:
                    logger.warning("Failed to close container %s: %s", container_id, e)

    async def prefetch_container(self, x: int, y: int, z: int) -> None:
        """Pre-fetch container data.

        Not implemented for WebSocket mode (no pre-fetch capability yet).
        """
        pass  # mineflayer mode has no pre-fetch yet
