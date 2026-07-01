"""Abstract Baritone adapter — pathfinding interface.

Ported from VMTools-v3 BaritoneAdapter.java. In MCC mode, implementations
use MoveTo + position polling instead of Baritone API.
"""
from __future__ import annotations

from abc import ABC, abstractmethod


class AbstractBaritoneAdapter(ABC):
    """Interface for pathfinding and movement."""

    @abstractmethod
    async def path_to_near(self, x: int, y: int, z: int, radius: int) -> bool:
        """Path to near (x, y, z) within radius. Returns True if started."""
        ...

    @abstractmethod
    async def cancel_pathing(self) -> None:
        """Cancel current pathfinding."""
        ...

    @abstractmethod
    async def is_pathing(self) -> bool:
        """Check if currently pathfinding."""
        ...

    @abstractmethod
    async def is_arrived(self, x: int, y: int, z: int, radius: int) -> bool:
        """Check if arrived at (x, y, z) within radius."""
        ...

    @abstractmethod
    async def is_path_failed(self) -> bool:
        """Check if pathfinding failed."""
        ...

    @abstractmethod
    async def look_at(self, x: int, y: int, z: int) -> None:
        """Look at (x, y, z)."""
        ...
