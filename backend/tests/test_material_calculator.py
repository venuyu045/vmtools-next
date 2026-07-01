"""Tests for MaterialCalculator."""
import pytest
from vmtools_next.core.material_calculator import MaterialCalculator
from vmtools_next.core.dataclasses import ProjectionMaterialRequirement, MaterialCompareResult


class TestMaterialCalculator:
    """Test MaterialCalculator static methods."""

    def test_compare_basic(self):
        """Test basic material comparison."""
        requirements = [
            ProjectionMaterialRequirement(
                item_id="minecraft:stone",
                display_name="Stone",
                count=100,
            ),
            ProjectionMaterialRequirement(
                item_id="minecraft:oak_planks",
                display_name="Oak Planks",
                count=64,
            ),
        ]
        warehouse = {"minecraft:stone": 50}
        player = {"minecraft:stone": 20, "minecraft:oak_planks": 30}

        results = MaterialCalculator.compare(requirements, warehouse, player)

        assert len(results) == 2
        stone = results[0]
        assert stone.item_id == "minecraft:stone"
        assert stone.required == 100
        assert stone.available_in_warehouse == 50
        assert stone.in_player_inventory == 20
        assert stone.shortfall == 30  # 100 - 50 - 20

        planks = results[1]
        assert planks.item_id == "minecraft:oak_planks"
        assert planks.required == 64
        assert planks.available_in_warehouse == 0
        assert planks.in_player_inventory == 30
        assert planks.shortfall == 34  # 64 - 0 - 30

    def test_compare_all_satisfied(self):
        """Test when all materials are available."""
        requirements = [
            ProjectionMaterialRequirement(
                item_id="minecraft:stone",
                display_name="Stone",
                count=10,
            ),
        ]
        warehouse = {"minecraft:stone": 100}
        player = {"minecraft:stone": 50}

        results = MaterialCalculator.compare(requirements, warehouse, player)

        assert len(results) == 1
        assert results[0].shortfall == -140  # 10 - 100 - 50
        assert results[0].is_satisfied is True

    def test_compare_empty(self):
        """Test with empty requirements."""
        results = MaterialCalculator.compare([], {"minecraft:stone": 100}, {})
        assert len(results) == 0

    def test_get_shortfall_items(self):
        """Test filtering items with shortfall."""
        results = [
            MaterialCompareResult(
                item_id="minecraft:stone",
                display_name="Stone",
                required=100,
                available_in_warehouse=50,
                in_player_inventory=20,
                shortfall=30,
            ),
            MaterialCompareResult(
                item_id="minecraft:oak_planks",
                display_name="Oak Planks",
                required=64,
                available_in_warehouse=100,
                in_player_inventory=0,
                shortfall=-36,
            ),
        ]

        shortfall = MaterialCalculator.get_shortfall_items(results)
        assert len(shortfall) == 1
        assert shortfall[0].item_id == "minecraft:stone"

    def test_get_shortfall_items_all_satisfied(self):
        """Test when all items are satisfied."""
        results = [
            MaterialCompareResult(
                item_id="minecraft:stone",
                display_name="Stone",
                required=10,
                available_in_warehouse=100,
                in_player_inventory=0,
                shortfall=-90,
            ),
        ]

        shortfall = MaterialCalculator.get_shortfall_items(results)
        assert len(shortfall) == 0

    def test_get_restock_list(self):
        """Test generating restock list."""
        results = [
            MaterialCompareResult(
                item_id="minecraft:stone",
                display_name="Stone",
                required=100,
                available_in_warehouse=80,
                in_player_inventory=0,
                shortfall=20,
            ),
            MaterialCompareResult(
                item_id="minecraft:oak_planks",
                display_name="Oak Planks",
                required=64,
                available_in_warehouse=100,
                in_player_inventory=0,
                shortfall=-36,
            ),
        ]

        restock = MaterialCalculator.get_restock_list(results)
        assert len(restock) == 1
        assert restock[0][0] == "minecraft:stone"
        assert restock[0][2] == 20  # min(shortfall, available_in_warehouse)

    def test_get_restock_list_limited_by_warehouse(self):
        """Test restock list limited by warehouse availability."""
        results = [
            MaterialCompareResult(
                item_id="minecraft:stone",
                display_name="Stone",
                required=100,
                available_in_warehouse=10,
                in_player_inventory=0,
                shortfall=90,
            ),
        ]

        restock = MaterialCalculator.get_restock_list(results)
        assert len(restock) == 1
        assert restock[0][2] == 10  # limited by warehouse availability

    def test_merge_snapshot_materials(self):
        """Test merging multiple snapshots."""
        snapshots = [
            {"minecraft:stone": 50, "minecraft:oak_planks": 30},
            {"minecraft:stone": 30, "minecraft:dirt": 20},
        ]

        merged = MaterialCalculator.merge_snapshot_materials(snapshots)
        assert merged["minecraft:stone"] == 80
        assert merged["minecraft:oak_planks"] == 30
        assert merged["minecraft:dirt"] == 20

    def test_merge_empty_snapshots(self):
        """Test merging empty snapshots."""
        merged = MaterialCalculator.merge_snapshot_materials([])
        assert len(merged) == 0

    def test_parse_inventory_slots(self):
        """Test parsing inventory slots."""
        slots = [
            {"type": "minecraft:stone", "count": 64, "slot": 0},
            {"type": "minecraft:oak_planks", "count": 32, "slot": 1},
            {"type": "minecraft:air", "count": 0, "slot": 2},
        ]

        result = MaterialCalculator.parse_inventory_slots(slots)
        assert result["minecraft:stone"] == 64
        assert result["minecraft:oak_planks"] == 32
        assert "minecraft:air" not in result

    def test_parse_inventory_slots_empty(self):
        """Test parsing empty inventory."""
        result = MaterialCalculator.parse_inventory_slots([])
        assert len(result) == 0

    def test_parse_inventory_slots_zero_count(self):
        """Test parsing slots with zero count."""
        slots = [
            {"type": "minecraft:stone", "count": 0, "slot": 0},
        ]

        result = MaterialCalculator.parse_inventory_slots(slots)
        assert "minecraft:stone" not in result
