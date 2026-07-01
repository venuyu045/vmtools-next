"""Material Calculator — compares projection requirements vs available materials.

Ported from VMTools-v3 MaterialCalculator.java. Pure logic, no external dependencies.
"""
from __future__ import annotations

import logging
from typing import Optional

from vmtools_next.core.dataclasses import (
    ProjectionMaterialRequirement, MaterialCompareResult, MaterialStack,
)

logger = logging.getLogger("vmtools.material_calc")


class MaterialCalculator:
    """Calculates material requirements and shortfalls."""

    @staticmethod
    def compare(
        requirements: list[ProjectionMaterialRequirement],
        warehouse_materials: dict[str, int],  # item_id → count in warehouse
        player_inventory: dict[str, int],  # item_id → count in player inventory
    ) -> list[MaterialCompareResult]:
        """Compare projection requirements against available materials.

        Returns a list of MaterialCompareResult, one per required material type.
        """
        results = []
        for req in requirements:
            available = warehouse_materials.get(req.item_id, 0)
            in_inventory = player_inventory.get(req.item_id, 0)
            shortfall = req.count - available - in_inventory
            results.append(MaterialCompareResult(
                item_id=req.item_id,
                display_name=req.display_name,
                required=req.count,
                available_in_warehouse=available,
                in_player_inventory=in_inventory,
                shortfall=shortfall,
            ))
        return results

    @staticmethod
    def get_shortfall_items(
        compare_results: list[MaterialCompareResult],
    ) -> list[MaterialCompareResult]:
        """Filter to only items with shortfall > 0."""
        return [r for r in compare_results if r.shortfall > 0]

    @staticmethod
    def get_restock_list(
        compare_results: list[MaterialCompareResult],
    ) -> list[tuple[str, str, int]]:
        """Generate a restock list: [(item_id, display_name, count_to_fetch), ...]"""
        restock = []
        for r in compare_results:
            if r.shortfall > 0:
                # Need to fetch from warehouse: shortfall items
                fetch_count = min(r.shortfall, r.available_in_warehouse)
                if fetch_count > 0:
                    restock.append((r.item_id, r.display_name, fetch_count))
        return restock

    @staticmethod
    def merge_snapshot_materials(
        snapshots: list[dict[str, int]],
    ) -> dict[str, int]:
        """Merge multiple container snapshots into a single material count dict."""
        merged: dict[str, int] = {}
        for snapshot in snapshots:
            for item_id, count in snapshot.items():
                merged[item_id] = merged.get(item_id, 0) + count
        return merged

    @staticmethod
    def parse_inventory_slots(slots: list[dict]) -> dict[str, int]:
        """Parse inventory slots from MCC GetInventorySnapshot response.

        Returns {item_id: total_count} aggregated across all slots.
        """
        result: dict[str, int] = {}
        for slot in slots:
            item_type = slot.get("type", "")
            count = slot.get("count", 0)
            if item_type and item_type != "minecraft:air" and count > 0:
                result[item_type] = result.get(item_type, 0) + count
        return result
