"""Tests for core dataclasses and material calculator."""
import pytest
from vmtools_next.core.dataclasses import (
    ProjectionInfo, ProjectionMaterialRequirement, MaterialCompareResult,
    MaterialStack, ContainerSnapshot, TravelTarget, TeleportCommandTemplate,
    PathingStatus, PrinterStatus, CheckResult, OperationType,
)
from vmtools_next.core.material_calculator import MaterialCalculator


class TestDataclasses:
    def test_projection_info(self):
        info = ProjectionInfo(name="test", total_blocks=100)
        assert info.name == "test"
        assert info.total_blocks == 100

    def test_material_stack(self):
        stack = MaterialStack(item_id="minecraft:stone", count=64)
        assert stack.item_id == "minecraft:stone"
        assert stack.count == 64

    def test_travel_target(self):
        target = TravelTarget(x=100, y=64, z=200, purpose="WAREHOUSE")
        assert target.x == 100
        assert target.purpose == "WAREHOUSE"

    def test_teleport_command_template(self):
        template = TeleportCommandTemplate(template="/tp {player} {x} {y} {z}")
        cmd = template.format("Steve", 100, 64, 200)
        assert cmd == "/tp Steve 100 64 200"

    def test_pathing_status_enum(self):
        assert PathingStatus.IDLE.name == "IDLE"
        assert PathingStatus.ARRIVED.name == "ARRIVED"

    def test_printer_status_enum(self):
        assert PrinterStatus.BUILDING.name == "BUILDING"

    def test_check_result_enum(self):
        assert CheckResult.OK.name == "OK"
        assert CheckResult.EMERGENCY_STOP.name == "EMERGENCY_STOP"


class TestMaterialCalculator:
    def test_compare(self):
        reqs = [
            ProjectionMaterialRequirement(item_id="minecraft:stone", display_name="Stone", count=100),
            ProjectionMaterialRequirement(item_id="minecraft:oak_planks", display_name="Oak Planks", count=50),
        ]
        warehouse = {"minecraft:stone": 80, "minecraft:oak_planks": 60}
        player = {"minecraft:stone": 10}

        results = MaterialCalculator.compare(reqs, warehouse, player)
        assert len(results) == 2

        stone = results[0]
        assert stone.item_id == "minecraft:stone"
        assert stone.required == 100
        assert stone.available_in_warehouse == 80
        assert stone.in_player_inventory == 10
        assert stone.shortfall == 10

        planks = results[1]
        assert planks.shortfall == -10  # More than needed

    def test_get_shortfall_items(self):
        results = [
            MaterialCompareResult("a", "A", 100, 80, 10, 10),
            MaterialCompareResult("b", "B", 50, 60, 0, -10),
        ]
        shortfall = MaterialCalculator.get_shortfall_items(results)
        assert len(shortfall) == 1
        assert shortfall[0].item_id == "a"

    def test_get_restock_list(self):
        results = [
            MaterialCompareResult("a", "A", 100, 80, 10, 10),
            MaterialCompareResult("b", "B", 50, 60, 0, -10),
        ]
        restock = MaterialCalculator.get_restock_list(results)
        assert len(restock) == 1
        assert restock[0][0] == "a"
        assert restock[0][2] == 10  # min(shortfall, available)

    def test_merge_snapshot_materials(self):
        snapshots = [
            {"minecraft:stone": 50, "minecraft:dirt": 30},
            {"minecraft:stone": 50, "minecraft:oak_planks": 20},
        ]
        merged = MaterialCalculator.merge_snapshot_materials(snapshots)
        assert merged["minecraft:stone"] == 100
        assert merged["minecraft:dirt"] == 30
        assert merged["minecraft:oak_planks"] == 20

    def test_parse_inventory_slots(self):
        slots = [
            {"type": "minecraft:stone", "count": 64, "slot": 0},
            {"type": "minecraft:stone", "count": 32, "slot": 1},
            {"type": "minecraft:air", "count": 0, "slot": 2},
        ]
        result = MaterialCalculator.parse_inventory_slots(slots)
        assert result["minecraft:stone"] == 96
        assert "minecraft:air" not in result
