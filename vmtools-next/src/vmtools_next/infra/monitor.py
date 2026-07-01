"""System Monitor — collects CPU, memory, disk, and network metrics.

Uses psutil to collect system metrics at regular intervals.
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Optional

import psutil

logger = logging.getLogger("vmtools.monitor")


class MonitorCollector:
    """Collects system metrics at regular intervals."""

    def __init__(self, interval_seconds: int = 10):
        self._interval = interval_seconds
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._metrics: list[dict] = []
        self._max_metrics = 10000

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._collect_loop())
        logger.info("Monitor started (interval=%ds)", self._interval)

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()

    def get_metrics(self, count: int = 100) -> list[dict]:
        return self._metrics[-count:]

    def get_latest(self) -> Optional[dict]:
        return self._metrics[-1] if self._metrics else None

    async def _collect_loop(self) -> None:
        while self._running:
            try:
                metrics = self._collect_system_metrics()
                self._metrics.append(metrics)
                if len(self._metrics) > self._max_metrics:
                    self._metrics = self._metrics[-self._max_metrics:]
            except Exception as e:
                logger.warning("Metrics collection error: %s", e)
            await asyncio.sleep(self._interval)

    def _collect_system_metrics(self) -> dict:
        """Collect current system metrics."""
        cpu_percent = psutil.cpu_percent(interval=0)
        memory = psutil.virtual_memory()
        disk = psutil.disk_usage("/")

        # Network I/O (delta since last call)
        net = psutil.net_io_counters()

        return {
            "timestamp": time.time(),
            "cpu_percent": cpu_percent,
            "memory_total": memory.total,
            "memory_used": memory.used,
            "memory_percent": memory.percent,
            "disk_total": disk.total,
            "disk_used": disk.used,
            "disk_percent": disk.percent,
            "net_bytes_sent": net.bytes_sent,
            "net_bytes_recv": net.bytes_recv,
        }
