"""Phase 1 shared fixtures: synthetic .litematic file generator and MCP client setup."""

import gzip
import pytest
from pathlib import Path
import tempfile
import io
import random

import nbtlib
from nbtlib.tag import Compound, List as NbtList, Int, Byte, Long, String


# ============================================================
# pytest CLI options for MCP live tests
# ============================================================

def pytest_addoption(parser):
    parser.addoption("--run-live-mcp", action="store_true", default=False,
                     help="Run tests that require live MCC MCP bots")
    parser.addoption("--mcp-host", default="127.0.0.1")
    parser.addoption("--mcp-port", default=33333, type=int)


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "live_mcp: tests requiring live MCC MCP bot (skipped without --run-live-mcp)"
    )


# ---- Wool colors for map art simulation ----
WOOL_COLORS = [
    "minecraft:white_wool",
    "minecraft:orange_wool",
    "minecraft:magenta_wool",
    "minecraft:light_blue_wool",
    "minecraft:yellow_wool",
    "minecraft:lime_wool",
    "minecraft:pink_wool",
    "minecraft:gray_wool",
    "minecraft:light_gray_wool",
    "minecraft:cyan_wool",
    "minecraft:purple_wool",
    "minecraft:blue_wool",
    "minecraft:brown_wool",
    "minecraft:green_wool",
    "minecraft:red_wool",
    "minecraft:black_wool",
]


def _encode_block_states(indices: list[int], palette_size: int) -> list[int]:
    """Encode block indices into bit-packed longs (reverse of _decode_block_states).

    bits_per_entry = max(2, ceil(log2(palette_size)))
    """
    import math
    bits = max(2, math.ceil(math.log2(max(palette_size, 1))))
    entries_per_long = 64 // bits
    mask = (1 << bits) - 1

    longs = []
    for chunk_start in range(0, len(indices), entries_per_long):
        chunk = indices[chunk_start:chunk_start + entries_per_long]
        long_val = 0
        for i, idx in enumerate(chunk):
            long_val |= (idx & mask) << (i * bits)
        # Handle sign for unsigned 64-bit
        if long_val >= 2**63:
            long_val -= 2**64
        longs.append(long_val)
    return longs


def generate_synthetic_litematic(
    width: int = 128,
    height: int = 1,
    depth: int = 128,
    palette_colors: list[str] = None,
) -> Path:
    """Generate a synthetic .litematic file for performance testing.

    Args:
        width:  X dimension (128 for map art)
        height: Y dimension (1 for map art)
        depth:  Z dimension (128 for map art)
        palette_colors: block IDs to use (default: WOOL_COLORS)

    Returns:
        Path to the temporary .litematic file
    """
    if palette_colors is None:
        palette_colors = WOOL_COLORS

    total_blocks_count = width * height * depth

    # Build palette (add minecraft:air as index 0)
    palette_tags = NbtList[Compound]()
    air_tag = Compound()
    air_tag["Name"] = String("minecraft:air")
    palette_tags.append(air_tag)

    for color in palette_colors:
        tag = Compound()
        tag["Name"] = String(color)
        palette_tags.append(tag)

    # Generate block indices (random for realistic distribution)
    palette_size = len(palette_tags)
    indices = [random.randint(0, palette_size - 1) for _ in range(total_blocks_count)]

    # Encode into bit-packed longs
    encoded_states = _encode_block_states(indices, palette_size)

    # Build NBT structure
    root = Compound()

    # Metadata
    metadata = Compound()
    metadata["Name"] = String(f"Synthetic_{width}x{height}x{depth}")
    metadata["Author"] = String("Phase1Test")
    metadata["Description"] = String("Auto-generated test projection")
    metadata["RegionCount"] = Int(1)
    metadata["TotalBlocks"] = Int(total_blocks_count)
    metadata["TotalVolume"] = Int(total_blocks_count)
    metadata["TimeCreated"] = Long(1753714500)
    root["Metadata"] = metadata

    # Region
    region = Compound()
    # Position
    pos = Compound()
    pos["x"] = Int(0)
    pos["y"] = Int(64)
    pos["z"] = Int(0)
    region["Position"] = pos

    # Size
    size = Compound()
    size["x"] = Int(width)
    size["y"] = Int(height)
    size["z"] = Int(depth)
    region["Size"] = size

    # Palette
    region["BlockStatePalette"] = palette_tags

    # BlockStates
    states_tags = NbtList[Long]()
    for val in encoded_states:
        states_tags.append(Long(val))
    region["BlockStates"] = states_tags

    # Empty entities/tile entities
    region["TileEntities"] = NbtList[Compound]()
    region["Entities"] = NbtList[Compound]()
    region["PendingBlockTicks"] = NbtList[Compound]()
    region["PendingFluidTicks"] = NbtList[Compound]()

    regions = Compound()
    regions["Main"] = region
    root["Regions"] = regions

    # Write gzipped NBT — pass root directly to File (not wrapped under "")
    # nbtlib.File(root) copies root's items as the File's own items.
    tmp = tempfile.NamedTemporaryFile(suffix=".litematic", delete=False)
    tmp.close()
    nbt_file = nbtlib.File(root)
    nbt_file.root_name = ""
    nbt_file.gzipped = True
    nbt_file.save(tmp.name)

    return Path(tmp.name)


@pytest.fixture
def temp_litematic_128x128():
    """Generate a 128×128×1 synthetic .litematic file (standard map art)."""
    p = generate_synthetic_litematic(width=128, height=1, depth=128)
    yield p
    # Cleanup
    try:
        p.unlink()
    except Exception:
        pass


@pytest.fixture
def temp_litematic_64x64():
    """Generate a 64×64×1 synthetic .litematic file (small map art)."""
    p = generate_synthetic_litematic(width=64, height=1, depth=64)
    yield p
    try:
        p.unlink()
    except Exception:
        pass


@pytest.fixture
def temp_litematic_256x256():
    """Generate a 256×256×1 synthetic .litematic file (large map art, stress test)."""
    p = generate_synthetic_litematic(width=256, height=1, depth=256)
    yield p
    try:
        p.unlink()
    except Exception:
        pass


@pytest.fixture
def temp_litematic_32x32():
    """Generate a 32×32×1 synthetic .litematic file (tiny, fast)."""
    p = generate_synthetic_litematic(width=32, height=1, depth=32)
    yield p
    try:
        p.unlink()
    except Exception:
        pass
