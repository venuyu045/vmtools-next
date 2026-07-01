"""Inventory Scanner — reads player inventory via MCC MCP.

Ported from VMTools-v3 PlayerInventoryScanner.java. Uses
GetInventorySnapshot(inventoryId=0) to read player inventory.
"""
from __future__ import annotations

import logging
from typing import Optional

from vmtools_next.adapters.mcc.mcc_mcp_client import MccMcpClient, MccMcpError
from vmtools_next.core.dataclasses import MaterialStack

logger = logging.getLogger("vmtools.inventory_scanner")


class InventoryScanner:
    """Scans player inventory via MCC MCP."""

    def __init__(self, mcc: MccMcpClient):
        self._mcc = mcc

    async def scan(self) -> dict[str, int]:
        """Scan player inventory and return {item_id: count}."""
        try:
            result = await self._mcc.get_inventory_snapshot(inventory_id=0)
            items: dict[str, int] = {}
            for slot in result.get("items", []):
                item_type = slot.get("type", "")
                count = slot.get("count", 0)
                if item_type and item_type != "minecraft:air" and count > 0:
                    items[item_type] = items.get(item_type, 0) + count
            logger.info("Inventory scanned: %d item types", len(items))
            return items
        except MccMcpError as e:
            logger.warning("Inventory scan failed: %s", e)
            return {}

    async def get_empty_slots(self) -> list[int]:
        """Get list of empty slot indices in player inventory."""
        try:
            result = await self._mcc.get_inventory_snapshot(inventory_id=0)
            occupied = set()
            for slot in result.get("items", []):
                if slot.get("type", "") != "minecraft:air" and slot.get("count", 0) > 0:
                    occupied.add(slot.get("slot", -1))
            # Player inventory slots: 0-8 (hotbar), 9-35 (main), 36-39 (armor), 40 (offhand)
            all_slots = set(range(36))  # Hotbar + main inventory
            return sorted(all_slots - occupied)
        except MccMcpError as e:
            logger.warning("Failed to get empty slots: %s", e)
            return []

    async def get_item_count(self, item_id: str) -> int:
        """Get the count of a specific item in player inventory."""
        inv = await self.scan()
        return inv.get(item_id, 0)
