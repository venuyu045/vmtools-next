"""MCC Baritone Adapter — pathfinding via MCP MoveTo + position polling.

Replaces VMTools-v3 BaritoneAdapter (which used Baritone API via reflection).
In MCC mode, we call MoveTo for pathfinding and poll GetPlayerState for arrival detection.
"""
from __future__ import annotations

import logging
import math
from typing import Optional

from vmtools_next.adapters.abstract.baritone import AbstractBaritoneAdapter
from vmtools_next.adapters.mcc.mcc_mcp_client import MccMcpClient, MccMcpError
from vmtools_next.core.dataclasses import PathingStatus

logger = logging.getLogger("vmtools.mcc_baritone")


class MccBaritoneAdapter(AbstractBaritoneAdapter):
    """Pathfinding via MCC MCP MoveTo API."""

    def __init__(self, mcc: MccMcpClient):
        self._mcc = mcc
        self._goal: Optional[tuple[int, int, int]] = None
        self._status = PathingStatus.IDLE
        self._path_failed = False

    @property
    def status(self) -> PathingStatus:
        return self._status

    async def path_to_near(self, x: int, y: int, z: int, radius: int) -> bool:
        """Start pathfinding to near (x, y, z) within radius."""
        self._goal = (x, y, z)
        self._status = PathingStatus.PATHING
        self._path_failed = False

        try:
            result = await self._mcc.move_to(
                x, y, z,
                allow_unsafe=False,
                allow_direct_teleport=False,
                max_offset=radius,
                min_offset=0,
                timeout_ms=10000,
            )
            if result.get("success", False):
                self._status = PathingStatus.ARRIVED
                logger.info("Arrived at (%d, %d, %d)", x, y, z)
                return True
            else:
                self._status = PathingStatus.FAILED
                self._path_failed = True
                logger.warning("Pathfinding failed to (%d, %d, %d): %s", x, y, z, result)
                return False
        except MccMcpError as e:
            self._status = PathingStatus.FAILED
            self._path_failed = True
            logger.error("Pathfinding error to (%d, %d, %d): %s", x, y, z, e)
            return False

    async def cancel_pathing(self) -> None:
        """Cancel current pathfinding.

        MCC MCP has no cancel_move API, so we just reset state.
        The MoveTo call will timeout naturally.
        """
        self._goal = None
        self._status = PathingStatus.CANCELED
        logger.info("Pathfinding canceled")

    async def is_pathing(self) -> bool:
        """Check if currently pathfinding."""
        return self._status == PathingStatus.PATHING

    async def is_arrived(self, x: int, y: int, z: int, radius: int) -> bool:
        """Check if arrived at (x, y, z) within radius."""
        try:
            state = await self._mcc.get_player_state()
            if not state.get("success", False):
                return False
            loc = state.get("location", {})
            px, py, pz = loc.get("x", 0), loc.get("y", 0), loc.get("z", 0)
            dx = px - (x + 0.5)
            dy = py - y
            dz = pz - (z + 0.5)
            distance = math.sqrt(dx*dx + dy*dy + dz*dz)
            return distance <= radius
        except MccMcpError:
            return False

    async def is_path_failed(self) -> bool:
        """Check if pathfinding failed."""
        return self._path_failed

    async def look_at(self, x: int, y: int, z: int) -> None:
        """Look at (x, y, z)."""
        try:
            await self._mcc.look_at(float(x), float(y), float(z))
        except MccMcpError as e:
            logger.warning("LookAt failed: %s", e)
