"""⚠️ 兼容 shim —— 多 Bot 列式建造引擎已迁到 ``vmtools_next.core.map_art.column_engine``。

2026-10-28 架构重构：原 1951 行文件拆成

  - ``core/map_art/column_engine.py``  ``ColumnBuildLoop`` + ``MultiBotCoordinator``（列池编排）
  - ``core/map_art/runtime.py``        单 bot 能力基类（启动/放置/补货/睡觉/死亡复位）
  - ``core/map_art/base_coordinator.py`` 任务级公共编排（含缺块自动补放闭环）

本次重构同时修复的关键缺陷：
  - **列号 1-based 导致的整体偏移 1 格**（第 0 列/行永远不建）→ 统一 0-based
  - 列式模式支持运行中 ``add_bot`` / ``remove_bot``（列池自然收敛）
  - 暂停态能从 socket 正确推出 ``paused``（旧 ``_aggregate`` 是死代码）

本文件**只做 re-export**；新代码请直接 ``from vmtools_next.core.map_art import ...``。
"""

from __future__ import annotations

from vmtools_next.core.map_art.column_engine import (  # noqa: F401
    ColumnBuildLoop,
    MultiBotCoordinator,
)
from vmtools_next.core.map_art.registry import (  # noqa: F401
    get_multi_coordinator,
    register_multi_coordinator,
    unregister_multi_coordinator,
)
from vmtools_next.core.map_art.types import (  # noqa: F401
    ColumnRegion,
    SquadAssignment,
    SquadPlan,
    SquadState,
)

__all__ = [
    "ColumnRegion", "SquadState", "SquadPlan", "SquadAssignment",
    "ColumnBuildLoop", "MultiBotCoordinator",
    "get_multi_coordinator", "register_multi_coordinator", "unregister_multi_coordinator",
]
