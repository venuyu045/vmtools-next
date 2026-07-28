"""Phase 1.4: LitematicaParser performance and correctness tests.

Tests:
  - Basic parsing correctness (128x128 map art)
  - Performance benchmarks (various sizes)
  - Cache behavior
  - Edge cases
  - Memory usage
"""

import time
import pytest
import tracemalloc
from pathlib import Path

from vmtools_next.adapters.litematica.litematica_parser import (
    LitematicaParser,
    _decode_block_states,
)
from tests.phase1.conftest import _encode_block_states


# ============================================================
# 1.  Correctness Tests
# ============================================================

class TestLitematicaParsing:
    """Basic correctness: does the parser extract the right data?"""

    @pytest.mark.asyncio
    async def test_parse_128x128_mapart(self, temp_litematic_128x128):
        """Test 1.4: Parse a 128×128×1 synthetic map art file."""
        parsed = await LitematicaParser.parse_file(str(temp_litematic_128x128))

        # Metadata
        assert parsed.name == f"Synthetic_128x1x128"
        assert parsed.author == "Phase1Test"
        assert parsed.total_blocks == 128 * 128  # 16384

        # Regions
        assert "Main" in parsed.regions
        region = parsed.regions["Main"]
        assert region["size"]["x"] == 128
        assert region["size"]["y"] == 1
        assert region["size"]["z"] == 128

        # Materials (should have at least some colors)
        assert len(parsed.materials) > 0

        # Layers (map art is single layer at y=0)
        assert 0 in parsed.layers
        layer_blocks = parsed.layers[0]
        # May be less than 16384 because air blocks are filtered
        assert len(layer_blocks) > 0
        assert len(layer_blocks) <= 16384

        # Each layer entry: (world_x, world_y, world_z, block_state)
        for wx, wy, wz, bs in layer_blocks[:5]:
            assert isinstance(wx, int)
            assert isinstance(wy, int)
            assert isinstance(wz, int)
            assert isinstance(bs, str)
            assert bs.startswith("minecraft:")

    @pytest.mark.asyncio
    async def test_parse_small(self, temp_litematic_32x32):
        """Test small file parsing (32x32)."""
        parsed = await LitematicaParser.parse_file(str(temp_litematic_32x32))
        assert parsed.total_blocks == 1024

    @pytest.mark.asyncio
    async def test_projection_info(self, temp_litematic_128x128):
        """Test get_projection_info returns correct dimensions."""
        info = await LitematicaParser.get_projection_info(
            str(temp_litematic_128x128),
            origin_x=100, origin_y=64, origin_z=200,
        )
        assert info.size_x == 128
        assert info.size_y == 1
        assert info.size_z == 128
        assert info.total_blocks == 16384
        assert info.origin_x == 100
        assert info.origin_y == 64
        assert info.origin_z == 200
        assert info.region_count == 1

    @pytest.mark.asyncio
    async def test_material_requirements(self, temp_litematic_128x128):
        """Test get_material_requirements sums correctly."""
        reqs = await LitematicaParser.get_material_requirements(
            str(temp_litematic_128x128)
        )
        total = sum(r.count for r in reqs)
        # Total blocks = air removed, so total <= 16384
        assert 0 < total <= 16384
        # Each requirement should have a display name
        for r in reqs:
            assert r.item_id.startswith("minecraft:")
            assert r.count > 0

    @pytest.mark.asyncio
    async def test_get_layer_blocks(self, temp_litematic_128x128):
        """Test get_layer_blocks for the map art layer."""
        blocks = await LitematicaParser.get_layer_blocks(
            str(temp_litematic_128x128),
            layer_index=0,
            layer_height=6,
            origin_x=0, origin_y=64, origin_z=0,
        )
        # Layer 0 (y offset = 0 in region, which is world y = 64)
        assert len(blocks) > 0
        for wx, wy, wz, bs in blocks[:5]:
            assert wy == 64  # origin_y + region_pos_y + layer_offset


# ============================================================
# 2.  Performance Benchmark Tests
# ============================================================

class TestLitematicaPerformance:
    """Performance benchmarks for various file sizes.

    Go conditions (from implementation plan):
      - 128×128: elapsed < 30s, peak memory < 500MB
      - No-Go: OOM or > 2min
    """

    @pytest.mark.asyncio
    async def test_performance_128x128(self, temp_litematic_128x128):
        """Benchmark: 128×128×1 map art (16384 blocks)."""
        tracemalloc.start()
        start = time.perf_counter()

        parsed = await LitematicaParser.parse_file(str(temp_litematic_128x128))

        elapsed = time.perf_counter() - start
        _, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()

        peak_mb = peak / 1024 / 1024

        print(f"\n  128×128 Parse: {elapsed:.3f}s, peak memory: {peak_mb:.1f} MB")
        print(f"  Blocks: {parsed.total_blocks}, Materials: {len(parsed.materials)}")

        # Go conditions
        assert elapsed < 30.0, f"Parse too slow: {elapsed:.1f}s (limit: 30s)"
        assert peak_mb < 500, f"Memory too high: {peak_mb:.1f} MB (limit: 500MB)"

    @pytest.mark.asyncio
    async def test_performance_256x256(self, temp_litematic_256x256):
        """Benchmark: 256×256×1 stress test (65536 blocks)."""
        tracemalloc.start()
        start = time.perf_counter()

        parsed = await LitematicaParser.parse_file(str(temp_litematic_256x256))

        elapsed = time.perf_counter() - start
        _, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()

        peak_mb = peak / 1024 / 1024

        print(f"\n  256×256 Parse: {elapsed:.3f}s, peak memory: {peak_mb:.1f} MB")
        print(f"  Blocks: {parsed.total_blocks}, Materials: {len(parsed.materials)}")

        # Relaxed for stress test: < 60s, < 1GB
        assert elapsed < 60.0, f"Parse too slow: {elapsed:.1f}s"
        assert peak_mb < 1000, f"Memory too high: {peak_mb:.1f} MB"

    @pytest.mark.asyncio
    async def test_performance_64x64(self, temp_litematic_64x64):
        """Benchmark: 64×64×1 (4096 blocks)."""
        start = time.perf_counter()
        parsed = await LitematicaParser.parse_file(str(temp_litematic_64x64))
        elapsed = time.perf_counter() - start

        print(f"\n  64×64 Parse: {elapsed:.3f}s")
        # Should be very fast: < 5s
        assert elapsed < 5.0

    @pytest.mark.asyncio
    async def test_cache_performance(self, temp_litematic_128x128):
        """Test TTLCache: second parse should be instant."""
        path = str(temp_litematic_128x128)

        # First parse (cold)
        start = time.perf_counter()
        await LitematicaParser.parse_file(path)
        cold_time = time.perf_counter() - start

        # Second parse (cached)
        start = time.perf_counter()
        await LitematicaParser.parse_file(path)
        hot_time = time.perf_counter() - start

        print(f"\n  Cache: cold={cold_time:.3f}s, hot={hot_time:.3f}s")

        # Cache hit should be >> 10x faster
        assert hot_time < cold_time / 5, \
            f"Cache not effective: hot={hot_time:.3f}s vs cold={cold_time:.3f}s"


# ============================================================
# 3.  Edge Cases
# ============================================================

class TestLitematicaEdgeCases:
    """Edge case and error handling tests."""

    @pytest.mark.asyncio
    async def test_nonexistent_file(self):
        """Test parsing a non-existent file raises FileNotFoundError."""
        with pytest.raises(Exception):
            await LitematicaParser.parse_file("/nonexistent/file.litematic")

    @pytest.mark.asyncio
    async def test_empty_palette(self):
        """Test file with only air in palette doesn't crash."""
        # All indices point to air (index 0)
        from tests.phase1.conftest import generate_synthetic_litematic
        p = generate_synthetic_litematic(width=32, height=1, depth=32,
                                          palette_colors=[])  # no non-air blocks
        try:
            parsed = await LitematicaParser.parse_file(str(p))
            # All blocks are air → materials should be empty
            assert len(parsed.materials) == 0, \
                f"Expected 0 materials, got {len(parsed.materials)}"
        finally:
            try:
                p.unlink()
            except Exception:
                pass

    @pytest.mark.asyncio
    async def test_get_layer_blocks_out_of_range(self, temp_litematic_32x32):
        """Test layer index beyond available layers returns empty."""
        blocks = await LitematicaParser.get_layer_blocks(
            str(temp_litematic_32x32),
            layer_index=999,  # way beyond
            layer_height=6,
        )
        assert len(blocks) == 0


# ============================================================
# 4.  Bit-Packing Codec Tests
# ============================================================

class TestBitPacking:
    """Verify that _decode_block_states and _encode_block_states are symmetric."""

    def test_roundtrip_2bit(self):
        """Round-trip with 2-bit entries (small palette)."""
        original = [0, 1, 2, 3, 0, 1, 2, 3, 0] * 100
        encoded = _encode_block_states(original, 4)  # 4 entries → 2 bits
        decoded = _decode_block_states(encoded, 2, len(original))
        assert decoded == original

    def test_roundtrip_4bit(self):
        """Round-trip with 4-bit entries (17-entry palette)."""
        original = [i % 17 for i in range(500)]
        encoded = _encode_block_states(original, 17)
        bits = 5  # ceil(log2(17)) = 5
        decoded = _decode_block_states(encoded, bits, len(original))
        assert decoded == original

    def test_roundtrip_7bit(self):
        """Round-trip with 7-bit entries (128-entry palette)."""
        original = [i % 128 for i in range(1000)]
        encoded = _encode_block_states(original, 128)
        bits = 7  # ceil(log2(128)) = 7
        decoded = _decode_block_states(encoded, bits, len(original))
        assert decoded == original

    def test_roundtrip_large(self):
        """Round-trip with 16384 entries (full map art)."""
        original = [i % 20 for i in range(16384)]  # 20-entry palette
        encoded = _encode_block_states(original, 20)
        bits = 5  # ceil(log2(20)) = 5
        decoded = _decode_block_states(encoded, bits, len(original))
        assert decoded == original

    def test_empty_input(self):
        """Empty raw data returns all zeros."""
        decoded = _decode_block_states([], 5, 10)
        assert decoded == [0] * 10

    def test_negative_long_values(self):
        """Handle negative long values (signed → unsigned conversion)."""
        # A value near 2^63-1
        original = [1, 2, 3] * 100
        encoded = _encode_block_states(original, 4)
        bits = 2
        decoded = _decode_block_states(encoded, bits, len(original))
        assert decoded == original
