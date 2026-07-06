"""Abstract Litematica adapter — projection reading interface.

Ported from VMTools-v3 LitematicaAdapter.java. In MCC mode, implementations
use LitematicaParser for file-based parsing + GetWorldBlockAt for verification.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional

from vmtools_next.core.dataclasses import (
    ProjectionInfo, ProjectionMaterialRequirement, MaterialStack,
)


class AbstractLitematicaAdapter(ABC):
    """Interface for projection reading and block verification."""

    def set_current_layer(self, layer_index: int, layer_height: int = 6) -> None:
        """Set the current layer for block verification. Override if needed."""
        pass

    @abstractmethod
    async def get_projection_info(self) -> Optional[ProjectionInfo]:
        """Get metadata about the current projection."""
        ...

    @abstractmethod
    async def get_material_requirements(self) -> list[ProjectionMaterialRequirement]:
        """Get material requirements for the current projection."""
        ...

    @abstractmethod
    async def get_material_stacks(self) -> list[MaterialStack]:
        """Get material stacks (grouped by type)."""
        ...

    @abstractmethod
    async def get_material_type_count(self) -> int:
        """Get the number of distinct material types."""
        ...

    @abstractmethod
    async def get_total_item_count(self) -> int:
        """Get the total number of items required."""
        ...

    @abstractmethod
    async def is_block_correct(self, x: int, y: int, z: int) -> bool:
        """Check if the block at (x, y, z) matches the projection."""
        ...

    @abstractmethod
    async def get_missing_block_count(self) -> int:
        """Get the number of blocks that don't match the projection."""
        ...

    @abstractmethod
    async def get_extra_block_count(self) -> int:
        """Get the number of extra blocks not in the projection."""
        ...
