"""协调器注册表 + 工厂（column / strip 统一入口）。

重构前有两张独立注册表（``map_art_coordinator._active_coordinators`` 与
``multi_bot_coordinator._active_multi_coordinators``），API 需要 ``or`` 两个查询，
且「停止任务」时容易漏摘一张（幽灵协调器残留 → 暂停/停止静默不生效）。
现在只有一张表，``build_mode`` 只是协调器实例上的一个属性。
"""

from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger("vmtools.map_art.registry")

_COORDINATORS: dict[str, object] = {}

BUILD_MODE_COLUMN = "column"
BUILD_MODE_STRIP = "strip"


def resolve_build_mode(target=None) -> str:
    """build_mode 归一化（唯一默认值来源，默认 column）。"""
    raw = None
    if isinstance(target, str):
        raw = target
    elif target is not None:
        raw = getattr(target, "build_mode", None)
    mode = (raw or "").strip().lower()
    return mode if mode in (BUILD_MODE_COLUMN, BUILD_MODE_STRIP) else BUILD_MODE_COLUMN


def create_coordinator(task_id: str, projection_data: dict,
                       origin_x: int, origin_y: int, origin_z: int,
                       build_mode: str = BUILD_MODE_COLUMN):
    """按 build_mode 造协调器（延迟导入，避免循环依赖）。"""
    mode = resolve_build_mode(build_mode)
    if mode == BUILD_MODE_STRIP:
        from vmtools_next.core.map_art.strip_engine import MapArtCoordinator

        return MapArtCoordinator(task_id, projection_data, origin_x, origin_y, origin_z)
    from vmtools_next.core.map_art.column_engine import MultiBotCoordinator

    return MultiBotCoordinator(task_id, projection_data, origin_x, origin_y, origin_z)


def register_coordinator(task_id: str, coordinator) -> None:
    _COORDINATORS[task_id] = coordinator


def unregister_coordinator(task_id: str) -> None:
    _COORDINATORS.pop(task_id, None)


def resolve_coordinator(task_id: str):
    """取活跃协调器（不分模式）。"""
    return _COORDINATORS.get(task_id)


# ── 兼容旧接口（语义保持）──

def get_coordinator(task_id: str):
    """旧 ``map_art_coordinator.get_coordinator``：任何模式的活跃协调器。"""
    return _COORDINATORS.get(task_id)


def get_multi_coordinator(task_id: str):
    """旧 ``multi_bot_coordinator.get_multi_coordinator``：只返回列式协调器。"""
    from vmtools_next.core.map_art.column_engine import MultiBotCoordinator

    coord = _COORDINATORS.get(task_id)
    return coord if isinstance(coord, MultiBotCoordinator) else None


def register_multi_coordinator(task_id: str, coordinator) -> None:
    _COORDINATORS[task_id] = coordinator


def unregister_multi_coordinator(task_id: str) -> None:
    _COORDINATORS.pop(task_id, None)


def active_task_ids() -> list[str]:
    return list(_COORDINATORS.keys())
