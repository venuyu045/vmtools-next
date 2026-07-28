"""Map Art Build Coordinator — multi-bot 2D construction engine.

Orchestrates N bots building a single-layer 128×128 (or larger) map art
from a Litematica projection. Each bot gets a rectangular strip of rows
along the Z axis and runs an independent BotBuildLoop.

Key design (per implementation-plan.md Section 3):
  - Strip partition: regions split along Z, each bot covers full X [0, W-1]
  - Edge placement: bot stands z-1 (north edge), places southward
  - Independent loops: no inter-bot coordination needed (no overlapping regions)
  - Progress push: Socket.IO events every 2s or every 10 blocks placed
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Optional

from vmtools_next.adapters.mcc.mcc_mcp_client import MccMcpClient, MccMcpError
from vmtools_next.data.db import sio

logger = logging.getLogger("vmtools.map_art")


# ──────────────────────────────────────────────
# Data structures
# ──────────────────────────────────────────────

@dataclass
class Region:
    """Rectangular region assigned to one bot. Coordinates are inclusive."""
    x_start: int
    x_end: int
    z_start: int
    z_end: int

    @property
    def rows(self) -> int:
        return self.z_end - self.z_start + 1

    @property
    def block_count(self) -> int:
        return (self.x_end - self.x_start + 1) * self.rows


@dataclass
class BotProgress:
    """Per-bot runtime progress (in-memory, not DB-persisted every tick)."""
    bot_id: str
    region: Region
    state: str = "idle"           # idle|moving|placing|restocking|completed|offline
    blocks_placed: int = 0
    blocks_total: int = 0
    current_row: int = -1         # the Z-row currently being placed
    last_completed_x: int = -1    # last X placed on current row (for resume)
    place_rate: float = 0.0       # avg blocks/min
    _recent_places: list[float] = field(default_factory=list)  # timestamps for rate calc

    def record_place(self):
        now = time.monotonic()
        self._recent_places.append(now)
        # Keep last 60s
        cutoff = now - 60
        self._recent_places = [t for t in self._recent_places if t > cutoff]
        self.blocks_placed += 1
        if self._recent_places:
            elapsed_min = (now - self._recent_places[0]) / 60
            if elapsed_min > 0:
                self.place_rate = len(self._recent_places) / elapsed_min


@dataclass
class MapArtBuildState:
    """Immutable snapshot of the current build state for Socket.IO push."""
    task_id: str
    status: str
    total_blocks: int
    placed_blocks: int
    bots: list[dict]
    materials: dict[str, dict]    # item_id → {required, placed}
    elapsed_sec: float
    eta_sec: float = 0.0


# ──────────────────────────────────────────────
# Region partition
# ──────────────────────────────────────────────

def partition_rectangular(width: int, depth: int, n: int) -> list[Region]:
    """Split a W×D rectangle into N roughly equal strips along the Z axis.

    Args:
        width: X dimension (usually 128)
        depth: Z dimension (usually 128)
        n: number of bots

    Returns:
        List of Regions, each covering full width [0, width-1]
    """
    if n <= 0:
        return []
    rows_per_bot = depth // n
    remainder = depth % n
    regions = []
    z = 0
    for i in range(n):
        extra = 1 if i < remainder else 0
        h = rows_per_bot + extra
        regions.append(Region(0, width - 1, z, z + h - 1))
        z += h
    return regions


def assign_supply_boxes(
    regions: list[Region],
    origin_x: int, origin_y: int, origin_z: int,
) -> list[tuple[int, int, int]]:
    """Place a supply box at the midpoint of each region's north edge.

    Returns list of (x, y, z) for each region's supply box.
    """
    boxes = []
    for r in regions:
        mid_x = origin_x + (r.x_start + r.x_end) // 2
        box_z = origin_z + r.z_start - 2  # 2 blocks north of region start
        boxes.append((mid_x, origin_y, box_z))
    return boxes


# ──────────────────────────────────────────────
# BotBuildLoop — per-bot independent build loop
# ──────────────────────────────────────────────

class BotBuildLoop:
    """Single bot's independent construction loop.

    Walks rows Z = region.z_start .. region.z_end, placing blocks
    from north edge (standing at Z-1, facing south).
    """

    def __init__(
        self,
        bot_id: str,
        bot_name: str,
        task_id: str,
        region: Region,
        block_matrix: dict[tuple[int, int], str],   # (x, z) → block_id
        origin_x: int, origin_y: int, origin_z: int,
        mcp: MccMcpClient,
    ):
        self.bot_id = bot_id
        self.bot_name = bot_name
        self.task_id = task_id
        self.region = region
        self.block_matrix = block_matrix
        self.origin_x = origin_x
        self.origin_y = origin_y
        self.origin_z = origin_z
        self.mcp = mcp

        self.progress = BotProgress(bot_id=bot_id, region=region)
        self.progress.blocks_total = region.block_count

        self._paused = asyncio.Event()
        self._paused.set()     # start unpaused
        self._stopped = False
        self._current_item: Optional[str] = None  # item currently in hand

    # ── Control ──────────────────────────────

    async def pause(self):
        self._paused.clear()
        self.progress.state = "waiting"

    async def resume(self):
        self._paused.set()
        self.progress.state = "placing"

    async def stop(self):
        self._stopped = True
        self._paused.set()  # unblock so loop can exit

    # ── Main loop ────────────────────────────

    async def run(self):
        """Execute the edge-placement build loop for this bot's region."""
        logger.info("[%s] Build loop started: rows %d→%d",
                     self.bot_id, self.region.z_start, self.region.z_end)

        try:
            for row_z in range(self.region.z_start, self.region.z_end + 1):
                if self._stopped:
                    break

                self.progress.current_row = row_z
                world_z = self.origin_z + row_z

                # Position bot at north edge of current row
                await self._move_to_row_edge(row_z)

                # Place blocks in this row, grouped by color
                await self._place_row(row_z, world_z)

            if not self._stopped:
                self.progress.state = "completed"
                logger.info("[%s] Region complete: %d blocks placed",
                            self.bot_id, self.progress.blocks_placed)
        except MccMcpError as e:
            self.progress.state = "offline"
            logger.error("[%s] MCP error: %s", self.bot_id, e)
        except asyncio.CancelledError:
            self.progress.state = "offline"
        except Exception:
            logger.exception("[%s] Unexpected error in build loop", self.bot_id)
            self.progress.state = "offline"

    async def _move_to_row_edge(self, row_z: int):
        """Move bot to the north edge of the given row."""
        await self._paused.wait()
        if self._stopped:
            return
        self.progress.state = "moving"
        target_x = self.origin_x + self.region.x_start
        target_z = self.origin_z + row_z - 1  # stand 1 block north
        # TODO: Use baritone or teleport to move bot
        # For now, skip if already close

    async def _place_row(self, row_z: int, world_z: int):
        """Place all blocks in a single row, grouped by color."""
        await self._paused.wait()
        if self._stopped:
            return

        # Gather blocks for this row
        row_blocks: dict[str, list[int]] = {}  # color → [x, ...]
        for x in range(self.region.x_start, self.region.x_end + 1):
            block_id = self.block_matrix.get((x, row_z))
            if block_id and block_id != "minecraft:air":
                row_blocks.setdefault(block_id, []).append(x)

        self.progress.state = "placing"

        # Place color by color
        for block_id, x_positions in row_blocks.items():
            await self._paused.wait()
            if self._stopped:
                return

            # Switch to correct item
            await self._ensure_item_in_hand(block_id)

            for x in x_positions:
                await self._paused.wait()
                if self._stopped:
                    return

                world_x = self.origin_x + x
                try:
                    await self.mcp.place_block(
                        x=world_x, y=self.origin_y, z=world_z,
                        face="SOUTH",
                        hand="MAIN_HAND",
                        look_at_block=False,
                    )
                    self.progress.record_place()
                    self.progress.last_completed_x = x
                except MccMcpError as e:
                    logger.warning("[%s] Place failed at (%d,%d,%d): %s",
                                   self.bot_id, world_x, self.origin_y, world_z, e)

    async def _ensure_item_in_hand(self, block_id: str):
        """Switch hotbar to the required block type."""
        if self._current_item == block_id:
            return
        try:
            # Strip properties for item matching: "minecraft:white_wool[facing=north]" → "minecraft:white_wool"
            clean_id = block_id.split("[")[0] if "[" in block_id else block_id
            await self.mcp.select_hotbar_item(clean_id)
            self._current_item = block_id
        except MccMcpError:
            logger.warning("[%s] Cannot switch to item: %s", self.bot_id, block_id)


# ──────────────────────────────────────────────
# MapArtCoordinator — orchestrator
# ──────────────────────────────────────────────

class MapArtCoordinator:
    """Orchestrates multi-bot map art construction.

    Lifecycle:
      1. start() → parse projection, partition regions, spawn BotBuildLoops
      2. Progress pushed every 2s via Socket.IO to room "build_{task_id}"
      3. pause() / resume() / stop() → fan out to all loops
      4. add_bot() / remove_bot() → dynamic region reassignment
    """

    def __init__(self, task_id: str, projection_data: dict,
                 origin_x: int, origin_y: int, origin_z: int):
        self.task_id = task_id
        self.projection = projection_data
        self.origin = (origin_x, origin_y, origin_z)
        self._loops: dict[str, BotBuildLoop] = {}
        self._started_at: float = 0.0
        self._progress_task: Optional[asyncio.Task] = None
        self._block_matrix: dict[tuple[int, int], str] = {}

    # ── Build 2D matrix from projection layers ──

    @classmethod
    def build_2d_matrix(cls, layers: dict[int, list[tuple[int, int, int, str]]]) -> dict[tuple[int, int], str]:
        """Flatten 3D layer blocks into a 2D (x, z) → block_id matrix.

        Map art is single-layer (y offset 0), so this is straightforward.
        """
        matrix: dict[tuple[int, int], str] = {}
        for y_offset, blocks in layers.items():
            for wx, wy, wz, block_id in blocks:
                matrix[(wx, wz)] = block_id
        return matrix

    # ── Lifecycle ─────────────────────────────

    async def start(self, bot_mcps: dict[str, tuple[str, MccMcpClient]]):
        """Start build with N bots.

        Args:
            bot_mcps: {bot_id: (bot_name, MccMcpClient)}
        """
        self._started_at = time.monotonic()

        # Build 2D matrix
        layers = self.projection.get("layers", {})
        self._block_matrix = self.build_2d_matrix(layers)

        # Determine map size from projection
        size_x = self.projection.get("regions", {}).get("Main", {}).get("size", {}).get("x", 128)
        size_z = self.projection.get("regions", {}).get("Main", {}).get("size", {}).get("z", 128)

        n_bots = len(bot_mcps)
        if n_bots == 0:
            logger.error("[%s] No bots available", self.task_id)
            return

        # Partition
        regions = partition_rectangular(size_x, size_z, n_bots)

        # Spawn loops
        bot_ids = list(bot_mcps.keys())
        for i, bot_id in enumerate(bot_ids):
            bot_name, mcp = bot_mcps[bot_id]
            loop = BotBuildLoop(
                bot_id=bot_id,
                bot_name=bot_name,
                task_id=self.task_id,
                region=regions[i],
                block_matrix=self._block_matrix,
                origin_x=self.origin[0],
                origin_y=self.origin[1],
                origin_z=self.origin[2],
                mcp=mcp,
            )
            self._loops[bot_id] = loop
            asyncio.create_task(loop.run())

        # Start progress push loop
        self._progress_task = asyncio.create_task(self._push_loop())

        # Emit initial map data
        await self._emit_map_init(bot_mcps, regions, size_x, size_z)

        logger.info("[%s] Build started: %d bots, %d regions",
                     self.task_id, n_bots, len(regions))

    async def pause(self):
        await asyncio.gather(*(loop.pause() for loop in self._loops.values()))

    async def resume(self):
        await asyncio.gather(*(loop.resume() for loop in self._loops.values()))

    async def stop(self):
        await asyncio.gather(*(loop.stop() for loop in self._loops.values()))
        if self._progress_task:
            self._progress_task.cancel()

    # ── Progress & Socket.IO ──────────────────

    async def _push_loop(self):
        """Every 2 seconds, aggregate progress and push via Socket.IO."""
        try:
            while True:
                await asyncio.sleep(2)
                await self._push_progress()
        except asyncio.CancelledError:
            pass

    async def _push_progress(self):
        state = self._aggregate()
        room = f"build_{self.task_id}"
        await sio.emit("build_progress", state.__dict__, room=room)

        # Bot positions
        bot_data = []
        for bid, loop in self._loops.items():
            bot_data.append({
                "bot_id": bid,
                "bot_name": loop.bot_name,
                "state": loop.progress.state,
                "region": {
                    "x_start": loop.region.x_start,
                    "x_end": loop.region.x_end,
                    "z_start": loop.region.z_start,
                    "z_end": loop.region.z_end,
                },
                "blocks_placed": loop.progress.blocks_placed,
                "blocks_total": loop.progress.blocks_total,
                "current_row": loop.progress.current_row,
                "place_rate": loop.progress.place_rate,
            })
        await sio.emit("build_bot_status", {"task_id": self.task_id, "bots": bot_data}, room=room)

    async def _emit_map_init(self, bot_mcps, regions, size_x, size_z):
        """Push initial 3D map data to connected clients."""
        room = f"build_{self.task_id}"
        blocks = [
            {"x": x, "y": self.origin[1], "z": z, "expected": bid, "placed": False}
            for (x, z), bid in self._block_matrix.items()
        ]
        bots = [
            {
                "bot_id": bid,
                "name": name,
                "color": f"#{(hash(bid) & 0xFFFFFF):06x}",
                "region": {
                    "x_start": r.x_start, "x_end": r.x_end,
                    "z_start": r.z_start, "z_end": r.z_end,
                },
                "state": "idle",
            }
            for (bid, (name, _)), r in zip(bot_mcps.items(), regions)
        ]
        await sio.emit("build_map_init", {
            "task_id": self.task_id,
            "blocks": blocks,
            "bots": bots,
            "origin": {"x": self.origin[0], "y": self.origin[1], "z": self.origin[2]},
            "size": {"x": size_x, "z": size_z},
        }, room=room)

    def _aggregate(self) -> MapArtBuildState:
        total = sum(l.progress.blocks_total for l in self._loops.values())
        placed = sum(l.progress.blocks_placed for l in self._loops.values())
        elapsed = time.monotonic() - self._started_at
        rate = placed / (elapsed / 60) if elapsed > 0 else 0
        remaining = total - placed
        eta = (remaining / rate) * 60 if rate > 0 else 0

        bots = [{
            "bot_id": l.bot_id,
            "name": l.bot_name,
            "state": l.progress.state,
            "region": {
                "x_start": l.region.x_start, "x_end": l.region.x_end,
                "z_start": l.region.z_start, "z_end": l.region.z_end,
            },
            "placed": l.progress.blocks_placed,
            "total": l.progress.blocks_total,
            "current_row": l.progress.current_row,
            "rate": l.progress.place_rate,
        } for l in self._loops.values()]

        return MapArtBuildState(
            task_id=self.task_id,
            status="running",
            total_blocks=total,
            placed_blocks=placed,
            bots=bots,
            materials={},  # populated by API layer
            elapsed_sec=elapsed,
            eta_sec=eta,
        )


# ──────────────────────────────────────────────
# Global registry of active coordinators
# ──────────────────────────────────────────────

_active_coordinators: dict[str, MapArtCoordinator] = {}


def get_coordinator(task_id: str) -> Optional[MapArtCoordinator]:
    return _active_coordinators.get(task_id)


def register_coordinator(task_id: str, coordinator: MapArtCoordinator):
    _active_coordinators[task_id] = coordinator


def unregister_coordinator(task_id: str):
    _active_coordinators.pop(task_id, None)
