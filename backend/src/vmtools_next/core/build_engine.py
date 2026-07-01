"""Build Engine — block placement loop for a single layer.

Handles the BUILD_LAYER → VERIFY_LAYER → NEXT_LAYER cycle.
Separated from BuildStateMachine for modularity and testability.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Optional

from vmtools_next.adapters.mcc.mcc_mcp_client import MccMcpClient, MccMcpError
from vmtools_next.adapters.mcc.mcc_printer import MccPrinterAdapter
from vmtools_next.adapters.mcc.mcc_litematica import MccLitematicaAdapter
from vmtools_next.core.dataclasses import ProjectionInfo
from vmtools_next.core.operation_logger import OperationLogger, OperationType

logger = logging.getLogger("vmtools.build_engine")


class BuildEngine:
    """Block placement engine for a single layer."""

    def __init__(self, mcc: MccMcpClient, printer: MccPrinterAdapter,
                 litematica: MccLitematicaAdapter, op_logger: OperationLogger):
        self._mcc = mcc
        self._printer = printer
        self._litematica = litematica
        self._op_logger = op_logger

    async def build_layer(self, projection: ProjectionInfo, layer_index: int,
                           layer_height: int = 6) -> tuple[int, int]:
        """Place all blocks in a layer. Returns (placed_count, total_count)."""
        layer_blocks = await self._litematica.get_layer_blocks(
            projection.file_path,
            layer_index,
            layer_height,
            projection.origin_x,
            projection.origin_y,
            projection.origin_z,
        )

        if not layer_blocks:
            logger.info("Layer %d: no blocks to place", layer_index)
            return 0, 0

        self._printer.enable()
        placed = 0
        current_item = None

        for (wx, wy, wz, block_state) in layer_blocks:
            # Extract base item ID
            item_id = block_state.split("[")[0] if "[" in block_state else block_state

            # Select item if changed
            if item_id != current_item:
                try:
                    await self._mcc.select_hotbar_item(item_id, prefer_lowest_slot=True)
                    current_item = item_id
                except MccMcpError:
                    logger.warning("Item not in hotbar: %s", item_id)

            # Check if within printer range
            try:
                state = await self._mcc.get_player_state()
                loc = state.get("location", {})
                px, py, pz = loc.get("x", 0), loc.get("y", 0), loc.get("z", 0)
                import math
                dist = math.sqrt((px-wx)**2 + (py-wy)**2 + (pz-wz)**2)
                if dist > self._printer.get_range():
                    await self._mcc.move_to(wx, wy + 1, wz, max_offset=2, timeout_ms=10000)
            except MccMcpError:
                pass

            # Place block
            try:
                await self._mcc.place_block(wx, wy, wz, face="UP",
                                             hand="MAIN_HAND", look_at_block=True)
                placed += 1
            except MccMcpError as e:
                logger.warning("Failed to place at (%d,%d,%d): %s", wx, wy, wz, e)

            # Rate limit
            interval = self._printer.get_place_interval() * 0.05
            await asyncio.sleep(interval)

        self._printer.disable()

        logger.info("Layer %d: placed %d/%d blocks", layer_index, placed, len(layer_blocks))
        self._op_logger.log(OperationType.BUILD, details=f"Layer {layer_index}: {placed}/{len(layer_blocks)}")
        return placed, len(layer_blocks)

    async def verify_layer(self, projection: ProjectionInfo, layer_index: int,
                            layer_height: int = 6) -> tuple[int, int]:
        """Verify a layer. Returns (correct_count, missing_count)."""
        layer_blocks = await self._litematica.get_layer_blocks(
            projection.file_path,
            layer_index,
            layer_height,
            projection.origin_x,
            projection.origin_y,
            projection.origin_z,
        )

        if not layer_blocks:
            return 0, 0

        correct = 0
        missing = 0
        for (wx, wy, wz, expected_state) in layer_blocks:
            is_correct = await self._litematica.is_block_correct(wx, wy, wz)
            if is_correct:
                correct += 1
            else:
                missing += 1

        logger.info("Layer %d verify: %d correct, %d missing", layer_index, correct, missing)
        return correct, missing

    async def move_to_next_layer(self, projection: ProjectionInfo,
                                  next_layer_index: int,
                                  layer_height: int = 6) -> bool:
        """Move to the starting position of the next layer."""
        next_y = projection.origin_y + next_layer_index * layer_height
        try:
            await self._mcc.move_to(
                projection.origin_x, next_y, projection.origin_z,
                max_offset=3, timeout_ms=10000)
            return True
        except MccMcpError as e:
            logger.warning("Failed to move to layer %d: %s", next_layer_index, e)
            return False
