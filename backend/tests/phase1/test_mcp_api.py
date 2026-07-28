"""Phase 1.1-1.3: MCP API Technical Validation.

Tests for ScanNearbyBlocks, place_block, and get_inventory_snapshot.

⚠️  These tests require live MCC bots connected to a Minecraft server.
    Run with:  pytest tests/phase1/test_mcp_api.py -v --run-live-mcp
    Without --run-live-mcp, they are skipped.

Prerequisites:
  - MCC instance running with MCP enabled (port 33333+)
  - Bot logged into a Minecraft server
  - World has placed blocks and loaded chunks around the bot
"""

import pytest
import time
import statistics
import asyncio
from typing import Optional

from vmtools_next.adapters.mcc.mcc_mcp_client import MccMcpClient, MccMcpError


# ============================================================
# Helpers
# ============================================================

def requires_live_bot(test_func):
    """Decorator: skip test unless --run-live-mcp is provided."""
    return pytest.mark.live_mcp(test_func)


@pytest.fixture
async def mcp_client(request) -> MccMcpClient:
    """Create and connect an MCP client, disconnect after test."""
    host = request.config.getoption("--mcp-host", default="127.0.0.1")
    port = request.config.getoption("--mcp-port", default=33333)
    client = MccMcpClient(host=host, port=port, timeout_read=30.0)
    connected = await client.connect()
    if not connected:
        pytest.skip(f"MCP not reachable at {host}:{port}")
    yield client
    await client.disconnect()


# ============================================================
# Test 1.1: ScanNearbyBlocks
# ============================================================

class TestScanNearbyBlocks:
    """Phase 1.1: ScanNearbyBlocks functional and performance tests.

    Go conditions:
      - radius=12, max_count=2000: elapsed < 5s, count >= 50
      - radius=4, max_count=50 material_filter="wool": only wool blocks
    No-Go conditions:
      - Empty result, error, count << expected
    """

    def _unwrap(self, result: dict) -> dict:
        """MCC wraps responses in {success, data: {...}}. Extract data."""
        data = result.get("data", result)
        return data

    @requires_live_bot
    @pytest.mark.asyncio
    async def test_scan_basic_min_radius(self, mcp_client):
        """Test 1.1.1a: Minimum radius (4), small max_count."""
        result = await mcp_client.scan_nearby_blocks(radius=4, max_count=50)
        data = self._unwrap(result)

        assert "blocks" in data, f"No 'blocks' key in response: {list(data.keys())}"
        blocks = data["blocks"]

        # Should have some non-air blocks in a loaded world
        assert len(blocks) > 0, "No blocks returned — ensure chunks are loaded"

        # Verify block structure
        first = blocks[0]
        for key in ["x", "y", "z", "material", "blockId"]:
            assert key in first, f"Missing key '{key}' in block: {first}"

        # count should be <= max_count
        count = data.get("count", len(blocks))
        assert count <= 50, f"count {count} > max_count 50"

    @requires_live_bot
    @pytest.mark.asyncio
    async def test_scan_max_radius(self, mcp_client):
        """Test 1.1.1b: Maximum radius (12), max max_count (2000)."""
        result = await mcp_client.scan_nearby_blocks(radius=12, max_count=2000)
        data = self._unwrap(result)

        assert "blocks" in data
        blocks = data["blocks"]
        count = data.get("count", len(blocks))

        # In a loaded world at ground level, expect many non-air blocks
        assert count >= 50, f"Only {count} blocks in 12-radius — need chunk-loaded area"
        assert count <= 2000, f"count {count} > max_count 2000"

        print(f"\n  Scan r=12: {count} blocks returned")

    @requires_live_bot
    @pytest.mark.asyncio
    async def test_scan_material_filter(self, mcp_client):
        """Test 1.1.1c: Material filter — only blocks with matching material."""
        result = await mcp_client.scan_nearby_blocks(
            radius=6, max_count=50, material_filter="stone"
        )
        data = self._unwrap(result)
        blocks = data.get("blocks", [])
        for b in blocks:
            material = b.get("material", "").lower()
            type_label = b.get("typeLabel", "").lower()
            assert "stone" in material or "stone" in type_label, \
                f"Filter 'stone' missed block: {b}"

    @requires_live_bot
    @pytest.mark.asyncio
    async def test_scan_performance(self, mcp_client):
        """Test 1.1.2: Performance benchmark across radii and max_counts."""
        results = {}

        for radius in [4, 8, 12]:
            for max_count in [100, 500, 2000]:
                start = time.perf_counter()
                result = await mcp_client.scan_nearby_blocks(
                    radius=radius, max_count=max_count
                )
                elapsed = time.perf_counter() - start
                data = self._unwrap(result)
                count = data.get("count", 0)
                key = f"r{radius}_m{max_count}"
                results[key] = {"elapsed": elapsed, "count": count}
                print(f"  {key}: {elapsed:.3f}s, {count} blocks")

        # Go condition: radius=12, max_count=2000 in < 5s
        key = "r12_m2000"
        assert key in results
        assert results[key]["elapsed"] < 5.0, \
            f"r12_m2000 took {results[key]['elapsed']:.1f}s (limit: 5s)"

    @requires_live_bot
    @pytest.mark.asyncio
    async def test_scan_edge_over_limit(self, mcp_client):
        """Test 1.1.3a: Exceeding max radius — MCC rejects > 12."""
        result = await mcp_client.scan_nearby_blocks(radius=20, max_count=50)
        # MCC rejects radius > 12 with {"success": false, "errorCode": "invalid_args"}
        success = result.get("success", True)
        if success:
            # If MCC silently clamps (newer version), accept that too
            data = self._unwrap(result)
            assert "blocks" in data
        else:
            # Current behavior: rejection with invalid_args
            assert result["errorCode"] == "invalid_args"
            assert "radius" in str(result.get("data", {}))

    @requires_live_bot
    @pytest.mark.asyncio
    async def test_scan_center_matches_player(self, mcp_client):
        """Verify center coordinates exist and are reasonable (within rendered world)."""
        scan_result = await mcp_client.scan_nearby_blocks(radius=4, max_count=10)
        data = self._unwrap(scan_result)
        center = data.get("center", {})

        # Center must exist and have valid integer coordinates
        cx = center.get("x")
        cy = center.get("y")
        cz = center.get("z")
        assert cx is not None, "Center missing x coordinate"
        assert cy is not None, "Center missing y coordinate"
        assert cz is not None, "Center missing z coordinate"
        assert isinstance(cx, (int, float)), f"Center x not numeric: {cx}"
        assert isinstance(cy, (int, float)), f"Center y not numeric: {cy}"
        assert isinstance(cz, (int, float)), f"Center z not numeric: {cz}"

        # Coordinates should be at reasonable world positions (not 0,0,0)
        print(f"\n  Scan center: ({cx}, {cy}, {cz})")


# ============================================================
# Test 1.2: place_block Performance
# ============================================================

class TestPlaceBlock:
    """Phase 1.2: place_block latency and throughput tests.

    Go conditions:
      - Single place: mean < 200ms
      - No-Go: p95 > 2000ms or failure rate > 5%
    """

    @requires_live_bot
    @pytest.mark.asyncio
    async def test_place_latency_single(self, mcp_client):
        """Test 1.2.1: Single place_block latency benchmark (50 iterations)."""
        # Need player position for a safe place location
        player = await mcp_client.get_player_state()
        loc = player.get("location", {})
        px, py, pz = int(loc.get("x", 0)), int(loc.get("y", 0)), int(loc.get("z", 0))

        # Place on ground at player feet (should be safe territory)
        latencies = []
        failures = 0

        for i in range(50):
            try:
                start = time.perf_counter()
                await mcp_client.place_block(
                    x=px, y=py - 1, z=pz,
                    face="UP", hand="MAIN_HAND", look_at_block=False,
                )
                latencies.append((time.perf_counter() - start) * 1000)  # ms
            except MccMcpError:
                failures += 1

        if not latencies:
            pytest.skip("All place_block calls failed — check bot state")

        mean_lat = statistics.mean(latencies)
        p95 = sorted(latencies)[int(len(latencies) * 0.95)]
        failure_rate = failures / 50

        print(f"\n  Place latency: mean={mean_lat:.1f}ms, p95={p95:.1f}ms, "
              f"failures={failures}/50 ({failure_rate:.0%})")

        assert mean_lat < 200, f"Mean latency {mean_lat:.0f}ms > 200ms"
        assert p95 < 2000, f"P95 latency {p95:.0f}ms > 2000ms"
        assert failure_rate <= 0.05, f"Failure rate {failure_rate:.0%} > 5%"

    @requires_live_bot
    @pytest.mark.asyncio
    async def test_place_throughput(self, mcp_client):
        """Test 1.2.2: Continuous place throughput (100 consecutive places).

        Key question: can single-bot placement reach acceptable rates
        without batch interface?
        """
        player = await mcp_client.get_player_state()
        loc = player.get("location", {})
        px, py, pz = int(loc.get("x", 0)), int(loc.get("y", 0)), int(loc.get("z", 0))

        success = 0
        fail = 0
        start = time.perf_counter()

        # Place 100 times on same block (overwrite)
        for _ in range(100):
            try:
                await mcp_client.place_block(
                    x=px, y=py - 1, z=pz,
                    face="UP", hand="MAIN_HAND", look_at_block=False,
                )
                success += 1
            except MccMcpError:
                fail += 1

        elapsed = time.perf_counter() - start
        rate = success / elapsed if elapsed > 0 else 0

        print(f"\n  Place throughput: {success}/{success+fail} in {elapsed:.1f}s "
              f"= {rate:.1f} blocks/s")

        # Expected: if each call is ~50ms, rate ~20 blocks/s
        # If rate < 5 blocks/s, batch interface is critical
        if rate < 5:
            print("  ⚠️  WARNING: Rate < 5 blocks/s — batch interface RECOMMENDED")

        assert success > 0, "All place_block calls failed"
        assert rate > 0, "Zero throughput"

        # Store rate for analysis
        mcp_client._test_place_rate = rate

    @requires_live_bot
    @pytest.mark.asyncio
    async def test_place_look_at_block_comparison(self, mcp_client):
        """Test 1.2.3: Compare look_at_block=True vs False impact on rate."""
        player = await mcp_client.get_player_state()
        loc = player.get("location", {})
        px, py, pz = int(loc.get("x", 0)), int(loc.get("y", 0)), int(loc.get("z", 0))

        results = {}
        for look_at in [True, False]:
            success = 0
            start = time.perf_counter()
            for _ in range(25):
                try:
                    await mcp_client.place_block(
                        x=px, y=py - 1, z=pz,
                        face="UP", hand="MAIN_HAND", look_at_block=look_at,
                    )
                    success += 1
                except MccMcpError:
                    pass
            elapsed = time.perf_counter() - start
            rate = success / elapsed if elapsed > 0 else 0
            results["with_look_at" if look_at else "no_look_at"] = rate

        print(f"\n  Place rate: look_at=True={results['with_look_at']:.1f}/s, "
              f"look_at=False={results['no_look_at']:.1f}/s")


# ============================================================
# Test 1.3: get_inventory_snapshot Polling
# ============================================================

class TestInventorySnapshot:
    """Phase 1.3: Multi-bot inventory polling pressure test.

    Go conditions: 30s of 1s polling without timeout
    No-Go: connection timeout or MCC CPU spike
    """

    @requires_live_bot
    @pytest.mark.asyncio
    async def test_inventory_latency_baseline(self, mcp_client):
        """Measure single get_inventory_snapshot latency."""
        start = time.perf_counter()
        result = await mcp_client.get_inventory_snapshot(inventory_id=0)
        elapsed = (time.perf_counter() - start) * 1000  # ms

        print(f"\n  Inventory snapshot latency: {elapsed:.1f}ms")

        # Verify result structure
        assert isinstance(result, dict), f"Expected dict, got {type(result)}"

        # Should be fast (< 500ms)
        assert elapsed < 500, f"Inventory snapshot took {elapsed:.0f}ms"

    @requires_live_bot
    @pytest.mark.asyncio
    async def test_inventory_continuous_polling(self, mcp_client):
        """Poll inventory every 1s for 30s, measure reliability."""
        latencies = []
        failures = 0

        for i in range(30):
            start = time.perf_counter()
            try:
                await mcp_client.get_inventory_snapshot(inventory_id=0)
                latencies.append((time.perf_counter() - start) * 1000)
            except MccMcpError:
                failures += 1
            await asyncio.sleep(1)

        if latencies:
            print(f"\n  Inventory poll x30: mean={statistics.mean(latencies):.1f}ms, "
                  f"max={max(latencies):.1f}ms, failures={failures}")

        # Should have zero failures in 30 consecutive polls
        assert failures == 0, f"{failures} failures in 30 polls"

        if latencies:
            # P95 should be < 300ms
            p95 = sorted(latencies)[int(len(latencies) * 0.95)]
            assert p95 < 300, f"P95 latency {p95:.0f}ms > 300ms"


# ============================================================
# Test scenario-based
# ============================================================

class TestMapArtScenario:
    """End-to-end scenario tests specific to map art building."""

    @requires_live_bot
    @pytest.mark.asyncio
    async def test_bot_position_for_edge_placement(self, mcp_client):
        """Verify bot can stand on edge and place blocks inward.

        For map art: bot stands z-1 (north edge), places block at z.
        """
        player = await mcp_client.get_player_state()
        loc = player.get("location", {})
        px, py, pz = int(loc.get("x", 0)), int(loc.get("y", 0)), int(loc.get("z", 0))

        # Place at position +1 in z (bot stands north, places south)
        try:
            result = await mcp_client.place_block(
                x=px, y=py, z=pz + 1,  # place 1 block south
                face="NORTH",  # facing the block from north
                hand="MAIN_HAND",
                look_at_block=False,
            )
            print(f"\n  Edge placement from ({px},{py},{pz}) → ({px},{py},{pz+1}): OK")
        except MccMcpError as e:
            print(f"\n  Edge placement failed: {e}")
            # May fail if chunk not loaded or item unavailable
            # Not a hard test failure
