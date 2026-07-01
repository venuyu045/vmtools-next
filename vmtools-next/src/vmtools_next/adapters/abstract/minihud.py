"""Abstract MiniHud adapter — container reading interface.

Ported from VMTools-v3 MiniHudAdapter.java. In MCC mode, implementations
use OpenContainerAt + GetInventorySnapshot + CloseContainer.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional

from vmtools_next.core.dataclasses import MaterialStack


@dataclass
class ReadResult:
    """Result of reading a container's contents."""
    items: list[MaterialStack]
    success: bool
    source: str  # "minihud" | "mcc_mcp" | "direct"
    error: Optional[str] = None

    @staticmethod
    def ok(items: list[MaterialStack], source: str = "mcc_mcp") -> ReadResult:
        return ReadResult(items=items, success=True, source=source)

    @staticmethod
    def failed(error: str) -> ReadResult:
        return ReadResult(items=[], success=False, source="", error=error)


class AbstractMiniHudAdapter(ABC):
    """Interface for reading container contents."""

    @abstractmethod
    async def read_container_items(self, x: int, y: int, z: int,
                                    timeout_ms: int = 5000) -> ReadResult:
        """Read the contents of a container at (x, y, z).

        Returns ReadResult with items list. The container is opened,
        read, and closed within this call.
        """
        ...

    @abstractmethod
    async def prefetch_container(self, x: int, y: int, z: int) -> None:
        """Pre-fetch container data if supported (no-op in MCC mode)."""
        ...

    @abstractmethod
    def is_available(self) -> bool:
        """Check if the adapter is available."""
        ...
