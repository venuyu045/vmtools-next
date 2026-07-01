"""MCC Litematica Adapter — projection reading via LitematicaParser + MCP GetWorldBlockAt.

Replaces VMTools-v3 LitematicaAdapter (which accessed Litematica mod's in-memory data).
In MCC mode, we use LitematicaParser for file-based parsing and GetWorldBlockAt for block verification.
"""
from __future__ import annotations

import logging
from typing import Optional

from vmtools_next.adapters.abstract.litematica import AbstractLitematicaAdapter
from vmtools_next.adapters.mcc.mcc_mcp_client import MccMcpClient, MccMcpError
from vmtools_next.adapters.litematica.litematica_parser import LitematicaParser
from vmtools_next.core.dataclasses import (
    ProjectionInfo, ProjectionMaterialRequirement, MaterialStack,
)

logger = logging.getLogger("vmtools.mcc_litematica")


class MccLitematicaAdapter(AbstractLitematicaAdapter):
    """Projection reading via LitematicaParser + block verification via MCP."""

    def __init__(self, mcc: MccMcpClient):
        self._mcc = mcc
        self._file_path: Optional[str] = None
        self._projection_info: Optional[ProjectionInfo] = None

    async def load_projection(self, file_path: str,
                                origin_x: int = 0, origin_y: int = 0,
                                origin_z: int = 0) -> bool:
        """Load a .litematic file for the current build task."""
        try:
            self._file_path = file_path
            self._projection_info = await LitematicaParser.get_projection_info(
                file_path, origin_x, origin_y, origin_z
            )
            logger.info("Loaded projection: %s (%d blocks)",
                        self._projection_info.name, self._projection_info.total_blocks)
            return True
        except Exception as e:
            logger.error("Failed to load projection %s: %s", file_path, e)
            return False

    async def get_projection_info(self) -> Optional[ProjectionInfo]:
        return self._projection_info

    async def get_material_requirements(self) -> list[ProjectionMaterialRequirement]:
        if not self._file_path:
            return []
        return await LitematicaParser.get_material_requirements(self._file_path)

    async def get_material_stacks(self) -> list[MaterialStack]:
        reqs = await self.get_material_requirements()
        return [
            MaterialStack(item_id=r.item_id, display_name=r.display_name, count=r.count)
            for r in reqs
        ]

    async def get_material_type_count(self) -> int:
        reqs = await self.get_material_requirements()
        return len(reqs)

    async def get_total_item_count(self) -> int:
        reqs = await self.get_material_requirements()
        return sum(r.count for r in reqs)

    async def is_block_correct(self, x: int, y: int, z: int) -> bool:
        """Check if the block at (x, y, z) matches the projection."""
        if not self._file_path or not self._projection_info:
            return True  # No projection loaded, assume correct

        try:
            # Get expected block from projection
            layer_blocks = await LitematicaParser.get_layer_blocks(
                self._file_path,
                layer_index=0,  # Will need proper layer calculation
                layer_height=6,
                origin_x=self._projection_info.origin_x,
                origin_y=self._projection_info.origin_y,
                origin_z=self._projection_info.origin_z,
            )

            # Find expected block at this position
            expected = None
            for (wx, wy, wz, block_state) in layer_blocks:
                if wx == x and wy == y and wz == z:
                    expected = block_state.split("[")[0]  # Remove state properties
                    break

            if expected is None:
                return True  # Position not in projection, assume correct

            # Get actual block from world via MCP
            actual = await self._mcc.get_world_block_at(x, y, z)
            if not actual.get("success", False):
                return False

            actual_name = actual.get("name", "")
            return actual_name == expected

        except MccMcpError as e:
            logger.warning("Block verification failed at (%d,%d,%d): %s", x, y, z, e)
            return False

    async def get_missing_block_count(self) -> int:
        """Count blocks that don't match the projection."""
        if not self._file_path or not self._projection_info:
            return 0

        layer_blocks = await LitematicaParser.get_layer_blocks(
            self._file_path,
            layer_index=0,
            layer_height=6,
            origin_x=self._projection_info.origin_x,
            origin_y=self._projection_info.origin_y,
            origin_z=self._projection_info.origin_z,
        )

        missing = 0
        for (wx, wy, wz, expected_state) in layer_blocks:
            if not await self.is_block_correct(wx, wy, wz):
                missing += 1
        return missing

    async def get_extra_block_count(self) -> int:
        """Count extra blocks not in the projection."""
        # This requires scanning the world, which is expensive
        # For now, return 0 (can be implemented later)
        return 0
