"""Tests for container utilities."""
import pytest
from vmtools_next.core.container_utils import (
    is_container_block, is_shulker_box, get_container_type,
    CONTAINER_BLOCKS, SHULKER_BOXES,
)


class TestContainerUtils:
    def test_is_container_block(self):
        assert is_container_block("minecraft:chest") == True
        assert is_container_block("minecraft:barrel") == True
        assert is_container_block("minecraft:white_shulker_box") == True
        assert is_container_block("minecraft:stone") == False
        assert is_container_block("minecraft:air") == False

    def test_is_container_block_with_state(self):
        assert is_container_block("minecraft:chest[facing=north]") == True
        assert is_container_block("minecraft:stone[variant=granite]") == False

    def test_is_shulker_box(self):
        assert is_shulker_box("minecraft:shulker_box") == True
        assert is_shulker_box("minecraft:white_shulker_box") == True
        assert is_shulker_box("minecraft:chest") == False

    def test_get_container_type(self):
        assert get_container_type("minecraft:chest") == "chest"
        assert get_container_type("minecraft:trapped_chest") == "chest"
        assert get_container_type("minecraft:barrel") == "barrel"
        assert get_container_type("minecraft:white_shulker_box") == "shulker_box"
        assert get_container_type("minecraft:furnace") == "furnace"
        assert get_container_type("minecraft:dispenser") == "dispenser"
        assert get_container_type("minecraft:hopper") == "hopper"
        assert get_container_type("minecraft:stone") == "other"

    def test_container_blocks_count(self):
        assert len(CONTAINER_BLOCKS) > 20
        assert len(SHULKER_BOXES) == 17
