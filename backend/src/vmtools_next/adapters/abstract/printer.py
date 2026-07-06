"""Abstract Printer adapter — block placement interface.

Ported from VMTools-v3 PrinterAdapter.java. In MCC mode, implementations
use PlaceBlock for each block placement.
"""
from __future__ import annotations

from abc import ABC, abstractmethod

from vmtools_next.core.dataclasses import PrinterStatus


class AbstractPrinterAdapter(ABC):
    """Interface for block placement control."""

    @abstractmethod
    def is_available(self) -> bool:
        """Check if the adapter is available."""
        ...

    @abstractmethod
    def is_enabled(self) -> bool:
        """Check if the printer is enabled."""
        ...

    @abstractmethod
    def enable(self) -> None:
        """Enable the printer."""
        ...

    @abstractmethod
    def disable(self) -> None:
        """Disable the printer."""
        ...

    @abstractmethod
    def toggle(self) -> None:
        """Toggle the printer on/off."""
        ...

    @abstractmethod
    def get_range(self) -> int:
        """Get the placement range."""
        ...

    @abstractmethod
    def set_range(self, range: int) -> None:
        """Set the placement range."""
        ...

    @abstractmethod
    def get_blocks_per_tick(self) -> int:
        """Get blocks placed per tick."""
        ...

    @abstractmethod
    def set_blocks_per_tick(self, bpt: int) -> None:
        """Set blocks placed per tick."""
        ...

    @abstractmethod
    def get_place_interval(self) -> int:
        """Get the place interval in ticks."""
        ...

    @abstractmethod
    def set_place_interval(self, interval: int) -> None:
        """Set the place interval in ticks."""
        ...

    @abstractmethod
    def apply_build_defaults(self, range: int, speed: int) -> None:
        """Apply build defaults from configuration."""
        ...

    @abstractmethod
    def get_status(self) -> PrinterStatus:
        """Get the current printer status."""
        ...

    @abstractmethod
    def set_status(self, status: PrinterStatus) -> None:
        """Set the current printer status."""
        ...
