"""Mineflayer Litematica Adapter — projection reading and block validation.

Implements AbstractLitematicaAdapter.
Projection data is parsed locally via LitematicaParser (same as MCC mode).
World block validation uses MineflayerBridgeClient.get_world_block_at().
"""

from __future__ import annotations

import logging
from typing import Optional

from vmtools_next.adapters.abstract.litematica import AbstractLitematicaAdapter
from vmtools_next.adapters.litematica.litematica_parser import LitematicaParser
from vmtools_next.adapters.mineflayer.mineflayer_client import (
    MineflayerBridgeClient,
    MineflayerError,
)
from vmtools_next.core.dataclasses import (
    ProjectionInfo,
    ProjectionMaterialRequirement,
    MaterialStack,
)

logger = logging.getLogger("vmtools.mf_litematica")


class MfLitematicaAdapter(AbstractLitematicaAdapter):
    """Projection data via LitematicaParser, world validation via mineflayer."""

    def __init__(self, client: MineflayerBridgeClient):
        self._client = client
        self._file_path: Optional[str] = None
        self._projection_info: Optional[ProjectionInfo] = None
        self._current_layer = 0
        self._layer_height = 6

    def set_current_layer(self, layer_index: int, layer_height: int = 6) -> None:
        self._current_layer = layer_index
        self._layer_height = layer_height

    async def load_projection(self, file_path: str, origin_x: int = 0,
                               origin_y: int = 0, origin_z: int = 0) -> bool:
        """Load a .litematic file via LitematicaParser."""
        self._file_path = file_path
        parser = LitematicaParser(file_path)
        result = parser.parse()
        if result:
            self._projection_info = self._projection_from_parser(parser, file_path,
                                                                   origin_x, origin_y, origin_z)
            logger.info("Loaded projection: %s (%d blocks)",
                         self._projection_info.name, self._projection_info.total_blocks)
        else:
            logger.error("Failed to parse projection: %s", file_path)
        return result

    async def get_projection_info(self) -> Optional[ProjectionInfo]:
        return self._projection_info

    async def get_material_requirements(self) -> list[ProjectionMaterialRequirement]:
        if not self._file_path:
            return []
        parser = LitematicaParser(self._file_path)
        return parser.get_material_requirements()

    async def get_material_stacks(self) -> list[MaterialStack]:
        reqs = await self.get_material_requirements()
        return [
            MaterialStack(item_id=r.item_id, display_name=r.display_name,
                          count=r.count, slot=-1)
            for r in reqs
        ]

    async def get_material_type_count(self) -> int:
        reqs = await self.get_material_requirements()
        return len(reqs)

    async def get_total_item_count(self) -> int:
        reqs = await self.get_material_requirements()
        return sum(r.count for r in reqs)

    # ── 方块验证 ──

    async def is_block_correct(self, x: int, y: int, z: int) -> bool:
        """Compare the world block at (x,y,z) with the projection expectation."""
        if not self._file_path or not self._projection_info:
            return True  # 没有加载投影则假设正确

        expected = self._get_expected_block(x, y, z)
        if expected is None:
            return True  # 不在投影范围内

        if not self._client.is_connected:
            return False

        try:
            result = await self._client.get_world_block_at(x, y, z)
            actual_name = result.get("name", "air")
            # 只比较方块名称，忽略状态属性
            actual = actual_name.split("[")[0]
            expected = expected.split("[")[0]
            return actual == expected
        except MineflayerError:
            return False

    async def get_missing_block_count(self) -> int:
        """Count blocks that don't match the projection."""
        if not self._file_path or not self._projection_info:
            return 0

        parser = LitematicaParser(self._file_path)
        layer_blocks = parser.get_layer_blocks(
            self._current_layer, self._layer_height,
            self._projection_info.origin_x,
            self._projection_info.origin_y,
            self._projection_info.origin_z,
        )
        missing = 0
        for (wx, wy, wz, expected_state) in layer_blocks:
            correct = await self.is_block_correct(wx, wy, wz)
            if not correct:
                missing += 1
        return missing

    async def get_extra_block_count(self) -> int:
        """Count extra blocks not in the projection."""
        if not self._projection_info:
            return 0

        info = self._projection_info
        # 扫描投影包围盒内的非空气方块，检查是否在投影中
        ox, oy, oz = info.origin_x, info.origin_y, info.origin_z
        parser = LitematicaParser(self._file_path) if self._file_path else None
        count = 0
        limit = 0
        for y in range(oy, oy + info.size_y):
            for z in range(oz, oz + info.size_z):
                for x in range(ox, ox + info.size_x):
                    expected = parser.get_block_state_at(x, y, z) if parser else None
                    if expected is not None and expected != "air":
                        continue  # 投影期望有方块
                    correct = self.is_block_correct(x, y, z)
                    if not correct:
                        count += 1
                        limit += 1
                        if limit >= 256:
                            return count
        return count

    # ── 内部工具 ──

    def _get_expected_block(self, x: int, y: int, z: int) -> Optional[str]:
        """Get the expected block state from the projection at (x,y,z)."""
        if not self._file_path:
            return None
        parser = LitematicaParser(self._file_path)
        return parser.get_block_state_at(x, y, z)

    def _projection_from_parser(self, parser, file_path: str,
                                 ox: int, oy: int, oz: int) -> ProjectionInfo:
        """Convert LitematicaParser output to ProjectionInfo."""
        regions = parser.get_region_names() or []
        return ProjectionInfo(
            name=parser.get_name() or "Unknown",
            author=parser.get_author() or "",
            description="",
            total_blocks=parser.get_block_count(),
            total_volume=parser.get_volume(),
            size_x=parser.get_size()[0] if parser.get_size() else 0,
            size_y=parser.get_size()[1] if parser.get_size() else 0,
            size_z=parser.get_size()[2] if parser.get_size() else 0,
            region_count=len(regions),
            region_names=regions,
            origin_x=ox,
            origin_y=oy,
            origin_z=oz,
            file_path=file_path,
        )
