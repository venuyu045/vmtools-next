"""MCC Printer Adapter — block placement via MCP PlaceBlock.

Replaces VMTools-v3 PrinterAdapter (which controlled litematica-printer mod).
In MCC mode, we directly call PlaceBlock for each block. The adapter manages
build state (enabled/disabled) and configuration (range, speed).
"""
from __future__ import annotations

import logging
from typing import Optional

from vmtools_next.adapters.abstract.printer import AbstractPrinterAdapter
from vmtools_next.adapters.mcc.mcc_mcp_client import MccMcpClient, MccMcpError
from vmtools_next.core.dataclasses import PrinterStatus

logger = logging.getLogger("vmtools.mcc_printer")


class MccPrinterAdapter(AbstractPrinterAdapter):
    """Block placement via MCC MCP PlaceBlock API."""

    def __init__(self, mcc: MccMcpClient):
        self._mcc = mcc
        self._enabled = False
        self._range = 6
        self._blocks_per_tick = 1
        self._place_interval = 3  # ticks
        self._status = PrinterStatus.IDLE

    def is_available(self) -> bool:
        return self._mcc.is_connected

    def is_enabled(self) -> bool:
        return self._enabled

    def enable(self) -> None:
        self._enabled = True
        self._status = PrinterStatus.BUILDING
        logger.info("Printer enabled (range=%d, bpt=%d)", self._range, self._blocks_per_tick)

    def disable(self) -> None:
        self._enabled = False
        self._status = PrinterStatus.DISABLED
        logger.info("Printer disabled")

    def toggle(self) -> None:
        if self._enabled:
            self.disable()
        else:
            self.enable()

    def get_range(self) -> int:
        return self._range

    def set_range(self, range: int) -> None:
        self._range = max(1, min(16, range))

    def get_blocks_per_tick(self) -> int:
        return self._blocks_per_tick

    def set_blocks_per_tick(self, bpt: int) -> None:
        self._blocks_per_tick = max(1, min(64, bpt))

    def get_place_interval(self) -> int:
        return self._place_interval

    def set_place_interval(self, interval: int) -> None:
        self._place_interval = max(1, interval)

    def apply_build_defaults(self, range: int, speed: int) -> None:
        """Apply build defaults from configuration."""
        self._range = max(1, min(16, range))
        self._blocks_per_tick = max(1, min(64, speed))
        logger.info("Build defaults applied: range=%d, speed=%d", self._range, self._blocks_per_tick)

    def get_status(self) -> PrinterStatus:
        return self._status

    def set_status(self, status: PrinterStatus) -> None:
        self._status = status
