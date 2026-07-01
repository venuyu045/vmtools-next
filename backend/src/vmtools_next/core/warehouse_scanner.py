"""Warehouse Scanner — scans containers in a warehouse via MCC MCP.

Ported from VMTools-v3 WarehouseScanner.java with superwy patterns:
  - NBT backpressure: Semaphore(16) for concurrent container reads
  - Breakpoint resume: scan_status persists current position
  - Aisle projection: vector projection onto line segments for navigation
"""
from __future__ import annotations

import asyncio
import logging
import math
import time
from enum import Enum, auto
from typing import Callable, Optional, Awaitable

from vmtools_next.adapters.mcc.mcc_mcp_client import MccMcpClient, MccMcpError
from vmtools_next.adapters.abstract.minihud import AbstractMiniHudAdapter, ReadResult
from vmtools_next.core.dataclasses import MaterialStack, ContainerSnapshot
from vmtools_next.core.container_utils import is_container_block

logger = logging.getLogger("vmtools.warehouse_scanner")


class ScanState(Enum):
    IDLE = auto()
    SCANNING = auto()
    PAUSED = auto()
    COMPLETED = auto()
    FAILED = auto()
    CANCELED = auto()


# Progress callback: (scanned_count, total_count, current_container_pos)
ScanProgressCallback = Callable[[int, int, tuple[int, int, int]], Awaitable[None]]


def _project_point_onto_segment(
    px: float, pz: float,
    ax: float, az: float,
    bx: float, bz: float,
) -> tuple[float, float, float]:
    """Project point (px, pz) onto line segment (ax,az)→(bx,bz).

    Returns (proj_x, proj_z, t) where t is the parameter [0,1].
    """
    dx = bx - ax
    dz = bz - az
    length_sq = dx * dx + dz * dz
    if length_sq < 0.001:
        return ax, az, 0.0
    t = max(0.0, min(1.0, ((px - ax) * dx + (pz - az) * dz) / length_sq))
    return ax + t * dx, az + t * dz, t


def _distance_xz(x1: float, z1: float, x2: float, z2: float) -> float:
    dx = x2 - x1
    dz = z2 - z1
    return math.sqrt(dx * dx + dz * dz)


class WarehouseScanner:
    """Scans containers in a warehouse using MCC MCP."""

    def __init__(self, mcc: MccMcpClient, minihud: AbstractMiniHudAdapter,
                 max_concurrent: int = 16):
        self._mcc = mcc
        self._minihud = minihud
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._state = ScanState.IDLE
        self._progress_callback: Optional[ScanProgressCallback] = None
        self._pause_event = asyncio.Event()
        self._pause_event.set()  # Not paused initially
        self._cancel_requested = False
        self._scan_results: dict[str, ContainerSnapshot] = {}
        self._scan_queue: list[tuple[int, int, int]] = []
        self._current_index: int = 0

    @property
    def state(self) -> ScanState:
        return self._state

    @property
    def results(self) -> dict[str, ContainerSnapshot]:
        return dict(self._scan_results)

    def set_progress_callback(self, callback: ScanProgressCallback) -> None:
        self._progress_callback = callback

    async def pause(self) -> None:
        """Pause the scan."""
        if self._state == ScanState.SCANNING:
            self._state = ScanState.PAUSED
            self._pause_event.clear()
            logger.info("Scan paused at container %d/%d",
                        self._current_index, len(self._scan_queue))

    async def resume(self) -> None:
        """Resume a paused scan."""
        if self._state == ScanState.PAUSED:
            self._state = ScanState.SCANNING
            self._pause_event.set()
            logger.info("Scan resumed from container %d", self._current_index)

    async def cancel(self) -> None:
        """Cancel the scan."""
        self._cancel_requested = True
        self._pause_event.set()  # Unblock if paused
        self._state = ScanState.CANCELED
        logger.info("Scan canceled")

    def build_scan_queue(self, container_positions: list[tuple[int, int, int]],
                          aisle_lines: list[tuple[tuple[int, int, int], tuple[int, int, int]]],
                          ) -> list[tuple[int, int, int]]:
        """Build and sort the scan queue.

        Sort order: aisle_line_index → aisle_t (projection parameter) → y → x → z
        """
        if not aisle_lines:
            return sorted(container_positions, key=lambda p: (p[1], p[0], p[2]))

        # For each container, find nearest aisle point and compute sort key
        entries = []
        for (cx, cy, cz) in container_positions:
            best_aisle_idx = 0
            best_t = 0.0
            best_dist = float("inf")

            for i, ((ax, ay, az), (bx, by, bz)) in enumerate(aisle_lines):
                px, pz, t = _project_point_onto_segment(cx, cz, ax, az, bx, bz)
                dist = _distance_xz(cx, cz, px, pz)
                if dist < best_dist:
                    best_dist = dist
                    best_aisle_idx = i
                    best_t = t

            entries.append((best_aisle_idx, best_t, cy, cx, cz))

        entries.sort()
        self._scan_queue = [(cx, cy, cz) for (_, _, cy, cx, cz) in entries]
        return self._scan_queue

    async def start_scan(self, container_positions: list[tuple[int, int, int]],
                          aisle_lines: Optional[list[tuple[tuple[int, int, int], tuple[int, int, int]]]] = None,
                          start_index: int = 0) -> bool:
        """Start scanning containers.

        Args:
            container_positions: [(x, y, z), ...] of all containers to scan
            aisle_lines: Optional aisle line segments for sorting
            start_index: Resume from this index (for breakpoint resume)
        """
        if self._state == ScanState.SCANNING:
            logger.warning("Scan already in progress")
            return False

        self._cancel_requested = False
        self._scan_results.clear()
        self._current_index = start_index

        # Build queue
        if aisle_lines:
            self._scan_queue = self.build_scan_queue(container_positions, aisle_lines)
        else:
            self._scan_queue = sorted(container_positions, key=lambda p: (p[1], p[0], p[2]))

        if not self._scan_queue:
            logger.info("No containers to scan")
            self._state = ScanState.COMPLETED
            return True

        self._state = ScanState.SCANNING
        logger.info("Starting scan: %d containers (from index %d)",
                     len(self._scan_queue), start_index)

        # Run scan in background
        asyncio.create_task(self._scan_loop())
        return True

    async def _scan_loop(self) -> None:
        """Main scan loop with backpressure control."""
        total = len(self._scan_queue)
        scanned = 0

        for i in range(self._current_index, total):
            if self._cancel_requested:
                self._state = ScanState.CANCELED
                return

            # Wait if paused
            await self._pause_event.wait()

            self._current_index = i
            x, y, z = self._scan_queue[i]

            # Backpressure: wait if too many pending
            async with self._semaphore:
                result = await self._read_container(x, y, z)

            if result.success:
                key = f"{x},{y},{z}"
                self._scan_results[key] = ContainerSnapshot(
                    x=x, y=y, z=z,
                    items=result.items,
                    total_items=sum(item.count for item in result.items),
                    scanned_at=time.time(),
                )
                scanned += 1

            # Progress callback
            if self._progress_callback:
                try:
                    await self._progress_callback(scanned, total, (x, y, z))
                except Exception as e:
                    logger.warning("Progress callback error: %s", e)

            # Yield control
            await asyncio.sleep(0.01)

        self._state = ScanState.COMPLETED
        logger.info("Scan completed: %d/%d containers scanned", scanned, total)

    async def _read_container(self, x: int, y: int, z: int) -> ReadResult:
        """Read a single container with timeout."""
        try:
            return await asyncio.wait_for(
                self._minihud.read_container_items(x, y, z, timeout_ms=5000),
                timeout=8.0,
            )
        except asyncio.TimeoutError:
            return ReadResult.failed(f"Timeout reading container at ({x},{y},{z})")
        except Exception as e:
            return ReadResult.failed(f"Error: {e}")

    def get_material_summary(self) -> dict[str, int]:
        """Aggregate all scanned container contents into {item_id: count}."""
        summary: dict[str, int] = {}
        for snapshot in self._scan_results.values():
            for item in snapshot.items:
                summary[item.item_id] = summary.get(item.item_id, 0) + item.count
        return summary
