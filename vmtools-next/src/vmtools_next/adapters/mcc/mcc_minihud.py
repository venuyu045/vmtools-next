"""MCC MiniHud Adapter — reads container contents via MCP OpenContainer + GetInventorySnapshot.

Replaces VMTools-v3 MiniHudAdapter (which directly read MC container menus).
In MCC mode, we: 1) OpenContainerAt, 2) GetInventorySnapshot, 3) CloseContainer.
"""
from __future__ import annotations

import logging
from typing import Optional

from vmtools_next.adapters.abstract.minihud import AbstractMiniHudAdapter, ReadResult
from vmtools_next.adapters.mcc.mcc_mcp_client import MccMcpClient, MccMcpError
from vmtools_next.core.dataclasses import MaterialStack

logger = logging.getLogger("vmtools.mcc_minihud")


class MccMiniHudAdapter(AbstractMiniHudAdapter):
    """Read container contents via MCC MCP API."""

    def __init__(self, mcc: MccMcpClient):
        self._mcc = mcc

    def is_available(self) -> bool:
        return self._mcc.is_connected

    async def read_container_items(self, x: int, y: int, z: int,
                                    timeout_ms: int = 5000) -> ReadResult:
        """Open, read, and close a container at (x, y, z)."""
        try:
            # 1. Open container
            open_result = await self._mcc.open_container_at(x, y, z, timeout_ms=timeout_ms)
            if not open_result.get("success", False):
                return ReadResult.failed(f"Failed to open container: {open_result}")

            inv_id = open_result.get("inventoryId", 0)

            # 2. Read inventory snapshot
            snapshot = await self._mcc.get_inventory_snapshot(inv_id)
            items = []
            for slot in snapshot.get("items", []):
                item = MaterialStack(
                    item_id=slot.get("type", ""),
                    display_name=slot.get("displayName", ""),
                    count=slot.get("count", 0),
                    slot=slot.get("slot", -1),
                )
                items.append(item)

            # 3. Close container
            await self._mcc.close_container(inv_id, timeout_ms=3000)

            return ReadResult.ok(items, source="mcc_mcp")

        except MccMcpError as e:
            logger.warning("MCC read container failed at (%d,%d,%d): %s", x, y, z, e)
            return ReadResult.failed(str(e))
        except Exception as e:
            logger.error("Unexpected error reading container at (%d,%d,%d): %s", x, y, z, e)
            return ReadResult.failed(str(e))

    async def prefetch_container(self, x: int, y: int, z: int) -> None:
        """No-op in MCC mode (no prefetch concept)."""
        pass
