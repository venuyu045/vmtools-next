"""Logistics event pusher — emits Socket.IO events to connected clients.

Provides helper functions for pushing bot status, task progress, task logs,
and alerts to all connected Socket.IO clients.
"""
from __future__ import annotations

from vmtools_next.data.db import sio
from vmtools_next.infra.logging import get_logger

logger = get_logger("logistics_pusher")


async def push_bot_status(bot_id: str, status: str, location: dict = None,
                           health: float = 20.0, food: int = 20,
                           current_task_run_id: str = None,
                           current_build_task_id: str = None):
    """Push bot status update to all connected clients."""
    await sio.emit("bot_status_update", {
        "bot_id": bot_id,
        "status": status,
        "location": location,
        "health": health,
        "food": food,
        "current_task_run_id": current_task_run_id,
        "current_build_task_id": current_build_task_id,
    })


async def push_bot_connected(bot_id: str, name: str):
    """Push bot connected event."""
    await sio.emit("bot_connected", {"bot_id": bot_id, "name": name})


async def push_bot_disconnected(bot_id: str, reason: str = ""):
    """Push bot disconnected event."""
    await sio.emit("bot_disconnected", {"bot_id": bot_id, "reason": reason})


async def push_task_progress(run_id: str, template_id: str, bot_id: str,
                               state: str, progress: float, loop_count: int):
    """Push logistics task progress update."""
    await sio.emit("task_progress", {
        "run_id": run_id,
        "template_id": template_id,
        "bot_id": bot_id,
        "state": state,
        "progress": progress,
        "loop_count": loop_count,
    })


async def push_task_log(run_id: str, timestamp: str, level: str,
                          state: str, message: str):
    """Push logistics task log entry."""
    await sio.emit("task_log", {
        "run_id": run_id,
        "timestamp": timestamp,
        "level": level,
        "state": state,
        "message": message,
    })


async def push_task_completed(run_id: str, status: str, loop_count: int, duration: float):
    """Push logistics task completed event."""
    await sio.emit("task_completed", {
        "run_id": run_id,
        "status": status,
        "loop_count": loop_count,
        "duration": duration,
    })


async def push_build_progress(task_id: str, bot_id: str, status: str,
                                current_state: str, current_layer: int, total_layers: int):
    """Push build task progress update."""
    await sio.emit("build_progress", {
        "task_id": task_id,
        "bot_id": bot_id,
        "status": status,
        "current_state": current_state,
        "current_layer": current_layer,
        "total_layers": total_layers,
    })


async def push_build_layer_update(task_id: str, layer_index: int,
                                    placed_blocks: int, missing_blocks: int, status: str):
    """Push build layer update."""
    await sio.emit("build_layer_update", {
        "task_id": task_id,
        "layer_index": layer_index,
        "placed_blocks": placed_blocks,
        "missing_blocks": missing_blocks,
        "status": status,
    })


async def push_scan_progress(warehouse_id: str, status: str, progress: float,
                                scanned_containers: int, total_containers: int):
    """Push warehouse scan progress."""
    await sio.emit("scan_progress", {
        "warehouse_id": warehouse_id,
        "status": status,
        "progress": progress,
        "scanned_containers": scanned_containers,
        "total_containers": total_containers,
    })


async def push_alert(alert_type: str, severity: str, message: str, metric_value: float = 0):
    """Push alert to all connected clients."""
    await sio.emit("alert", {
        "type": alert_type,
        "severity": severity,
        "message": message,
        "metric_value": metric_value,
    })


async def push_metrics_update(timestamp: float, cpu_percent: float,
                                memory_percent: float, disk_percent: float):
    """Push metrics update to all connected clients."""
    await sio.emit("metrics_update", {
        "timestamp": timestamp,
        "cpu_percent": cpu_percent,
        "memory_percent": memory_percent,
        "disk_percent": disk_percent,
    })
