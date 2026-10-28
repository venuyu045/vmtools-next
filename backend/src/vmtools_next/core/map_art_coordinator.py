"""⚠️ 兼容 shim —— 地图画建造（strip 模式）已迁到 ``vmtools_next.core.map_art``。

2026-10-28 架构重构：4432 行的 ``map_art_coordinator.py`` 拆成

  - ``core/map_art/runtime.py``       ``BotRuntime``（单 bot 全部能力）
  - ``core/map_art/strip_engine.py``  ``StripBuildLoop`` + ``MapArtCoordinator``
  - ``core/map_art/base_coordinator.py`` 任务级公共编排
  - ``core/map_art/types|geometry|settings|store|activity|placement`` 基础层

本文件**只做 re-export**，保证历史 import 不断链（API / 调度器 / socket handler）。
新代码请直接 ``from vmtools_next.core.map_art import ...``。
"""

from __future__ import annotations

from vmtools_next.core.map_art.geometry import (  # noqa: F401
    assign_supply_boxes,
    build_2d_matrix,
    partition_rectangular,
    resolve_size,
)
from vmtools_next.core.map_art.registry import (  # noqa: F401
    get_coordinator,
    register_coordinator,
    resolve_build_mode,
    resolve_coordinator,
    unregister_coordinator,
)
from vmtools_next.core.map_art.runtime import BotRuntime  # noqa: F401
from vmtools_next.core.map_art.strip_engine import (  # noqa: F401
    MapArtCoordinator,
    StripBuildLoop,
)
from vmtools_next.core.map_art.types import (  # noqa: F401
    BotProgress,
    MapArtBuildState,
    Region,
)

# 历史类名：旧 ``BotBuildLoop`` = strip 模式单 bot 循环（现在叫 StripBuildLoop）。
# 保留别名是为了兼容 ``BotBuildLoop._normalize_item_id(...)`` 这类静态调用。
BotBuildLoop = StripBuildLoop

__all__ = [
    "Region", "BotProgress", "MapArtBuildState",
    "BotRuntime", "StripBuildLoop", "BotBuildLoop", "MapArtCoordinator",
    "partition_rectangular", "assign_supply_boxes", "build_2d_matrix", "resolve_size",
    "get_coordinator", "register_coordinator", "unregister_coordinator",
    "resolve_coordinator", "resolve_build_mode",
]
