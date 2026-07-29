"""Mineflayer Printer Adapter — block placement state management.

Implements AbstractPrinterAdapter. Like the MCC version, this is pure
state management — actual place_block calls are made by the orchestrator
directly through MineflayerBridgeClient.
"""

from __future__ import annotations

import logging

from vmtools_next.adapters.abstract.printer import AbstractPrinterAdapter
from vmtools_next.adapters.mineflayer.mineflayer_client import MineflayerBridgeClient
from vmtools_next.core.dataclasses import PrinterStatus

logger = logging.getLogger("vmtools.mf_printer")


class MfPrinterAdapter(AbstractPrinterAdapter):
    """Block placement state management via mineflayer."""

    def __init__(self, client: MineflayerBridgeClient):
        self._client = client
        self._enabled = False
        self._range = 6
        self._blocks_per_tick = 1
        self._place_interval = 3  # ticks
        self._status = PrinterStatus.IDLE

    def is_available(self) -> bool:
        return self._client.is_connected

    def is_enabled(self) -> bool:
        return self._enabled

    def enable(self) -> None:
        self._enabled = True
        self._status = PrinterStatus.BUILDING
        logger.info("MfPrinter enabled (range=%d, bpt=%d)", self._range, self._blocks_per_tick)

    def disable(self) -> None:
        self._enabled = False
        self._status = PrinterStatus.DISABLED
        logger.info("MfPrinter disabled")

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
        self._range = max(1, min(16, range))
        self._blocks_per_tick = max(1, min(64, speed))
        logger.info("MfPrinter build defaults: range=%d, speed=%d", self._range, self._blocks_per_tick)

    def get_status(self) -> PrinterStatus:
        return self._status

    def set_status(self, status: PrinterStatus) -> None:
        self._status = status
