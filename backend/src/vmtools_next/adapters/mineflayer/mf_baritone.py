"""Mineflayer Baritone Adapter — pathfinding via mineflayer-pathfinder.

Implements AbstractBaritoneAdapter using MineflayerBridgeClient WebSocket calls.
"""

from __future__ import annotations

import logging
from typing import Optional

from vmtools_next.adapters.abstract.baritone import AbstractBaritoneAdapter
from vmtools_next.adapters.mineflayer.mineflayer_client import (
    MineflayerBridgeClient,
    MineflayerError,
    MineflayerConnectionError,
)
from vmtools_next.core.dataclasses import PathingStatus

logger = logging.getLogger("vmtools.mf_baritone")


class MfBaritoneAdapter(AbstractBaritoneAdapter):
    """Pathfinding via mineflayer-pathfinder, communicated over WebSocket."""

    def __init__(self, client: MineflayerBridgeClient):
        self._client = client
        self._goal: Optional[tuple[int, int, int]] = None
        self._status = PathingStatus.IDLE
        self._path_failed = False

    @property
    def status(self) -> PathingStatus:
        return self._status

    async def path_to_near(self, x: int, y: int, z: int, radius: int) -> bool:
        """Pathfind to (x, y, z) within the given radius.

        Returns True if pathing was initiated (caller should check arrival).
        """
        self._goal = (x, y, z)
        self._status = PathingStatus.PATHING
        self._path_failed = False

        if not self._client.is_connected:
            self._status = PathingStatus.FAILED
            self._path_failed = True
            logger.warning("path_to_near: not connected")
            return False

        try:
            result = await self._client.move_to(x, y, z, max_offset=radius)
            # move_to 是阻塞的（内部 await goal_reached）
            if result.get("success"):
                self._status = PathingStatus.ARRIVED
                return True
            else:
                self._status = PathingStatus.FAILED
                self._path_failed = True
                return False
        except MineflayerError as e:
            self._status = PathingStatus.FAILED
            self._path_failed = True
            logger.warning("path_to_near failed: %s", e)
            return False

    async def cancel_pathing(self) -> None:
        """Cancel current pathfinding (mineflayer supports this natively)."""
        self._status = PathingStatus.CANCELED
        self._path_failed = False
        if self._client.is_connected:
            try:
                await self._client.cancel_pathing()
            except MineflayerError:
                pass

    async def is_pathing(self) -> bool:
        return self._status == PathingStatus.PATHING

    async def is_arrived(self, x: int, y: int, z: int, radius: int) -> bool:
        """Check if the bot has arrived at (x,y,z) within radius."""
        if not self._client.is_connected:
            return False
        try:
            state = await self._client.get_player_state()
            loc = state.get("location")
            if not loc:
                return False
            import math
            dist = math.sqrt((loc["x"] - x) ** 2 + (loc["y"] - y) ** 2 + (loc["z"] - z) ** 2)
            if dist <= radius:
                self._status = PathingStatus.ARRIVED
                return True
            return False
        except MineflayerError:
            return False

    async def is_path_failed(self) -> bool:
        return self._path_failed

    async def look_at(self, x: int, y: int, z: int) -> None:
        if not self._client.is_connected:
            logger.warning("look_at: not connected")
            return
        try:
            await self._client.look_at(x, y, z)
        except MineflayerError as e:
            logger.warning("look_at failed: %s", e)
