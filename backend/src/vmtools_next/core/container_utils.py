"""Container Utilities — container detection and shulker box recursion.

Ported from VMTools-v3 ContainerUtils.java. Provides:
  - is_container_block(): check if a block is a container
  - get_container_type(): get container type from block name
"""
from __future__ import annotations

CONTAINER_BLOCKS = {
    "minecraft:chest", "minecraft:trapped_chest", "minecraft:barrel",
    "minecraft:shulker_box", "minecraft:white_shulker_box", "minecraft:orange_shulker_box",
    "minecraft:magenta_shulker_box", "minecraft:light_blue_shulker_box",
    "minecraft:yellow_shulker_box", "minecraft:lime_shulker_box",
    "minecraft:pink_shulker_box", "minecraft:gray_shulker_box",
    "minecraft:light_gray_shulker_box", "minecraft:cyan_shulker_box",
    "minecraft:purple_shulker_box", "minecraft:blue_shulker_box",
    "minecraft:brown_shulker_box", "minecraft:green_shulker_box",
    "minecraft:red_shulker_box", "minecraft:black_shulker_box",
    "minecraft:dispenser", "minecraft:dropper", "minecraft:hopper",
    "minecraft:furnace", "minecraft:blast_furnace", "minecraft:smoker",
    "minecraft:brewing_stand", "minecraft:enchanting_table",
    "minecraft:anvil", "minecraft:chipped_anvil", "minecraft:damaged_anvil",
    "minecraft:loom", "minecraft:cartography_table", "minecraft:fletching_table",
    "minecraft:smithing_table", "minecraft:grindstone", "minecraft:stonecutter",
}

SHULKER_BOXES = {
    "minecraft:shulker_box", "minecraft:white_shulker_box", "minecraft:orange_shulker_box",
    "minecraft:magenta_shulker_box", "minecraft:light_blue_shulker_box",
    "minecraft:yellow_shulker_box", "minecraft:lime_shulker_box",
    "minecraft:pink_shulker_box", "minecraft:gray_shulker_box",
    "minecraft:light_gray_shulker_box", "minecraft:cyan_shulker_box",
    "minecraft:purple_shulker_box", "minecraft:blue_shulker_box",
    "minecraft:brown_shulker_box", "minecraft:green_shulker_box",
    "minecraft:red_shulker_box", "minecraft:black_shulker_box",
}


def is_container_block(block_name: str) -> bool:
    """Check if a block name represents a container."""
    base = block_name.split("[")[0] if "[" in block_name else block_name
    return base in CONTAINER_BLOCKS


def is_shulker_box(block_name: str) -> bool:
    """Check if a block name represents a shulker box."""
    base = block_name.split("[")[0] if "[" in block_name else block_name
    return base in SHULKER_BOXES


def get_container_type(block_name: str) -> str:
    """Get the container type from a block name."""
    base = block_name.split("[")[0] if "[" in block_name else block_name
    if base in ("minecraft:chest", "minecraft:trapped_chest"):
        return "chest"
    if base == "minecraft:barrel":
        return "barrel"
    if base in SHULKER_BOXES:
        return "shulker_box"
    if base in ("minecraft:furnace", "minecraft:blast_furnace", "minecraft:smoker"):
        return "furnace"
    if base in ("minecraft:dispenser", "minecraft:dropper"):
        return "dispenser"
    if base == "minecraft:hopper":
        return "hopper"
    return "other"
