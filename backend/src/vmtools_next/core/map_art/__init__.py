"""地图画建造引擎（2026-10-28 架构重构后的唯一实现）。

分层：

    types / geometry / settings     纯数据与纯函数（可单测，无 IO）
    activity / store                日志与持久化
    placement / runtime             单 bot 能力（放置语义唯一实现）
    strip_engine / column_engine    两种建造顺序
    base_coordinator / registry     任务级编排与注册表

外部（API / 调度器 / socket handler）请优先从这里 import；
``core/map_art_coordinator.py`` 与 ``core/multi_bot_coordinator.py`` 仅作为
历史兼容 shim 保留。
"""

from __future__ import annotations

from vmtools_next.core.map_art.activity import ActivityLog
from vmtools_next.core.map_art.base_coordinator import BaseCoordinator
from vmtools_next.core.map_art.column_engine import ColumnBuildLoop, MultiBotCoordinator
from vmtools_next.core.map_art.geometry import (
    assign_supply_boxes,
    build_2d_matrix,
    column_cells,
    partition_rectangular,
    plan_squad,
    region_cells,
    resolve_size,
    tile_ranges,
)
from vmtools_next.core.map_art.placement import ensure_stand, place_cell
from vmtools_next.core.map_art.registry import (
    BUILD_MODE_COLUMN,
    BUILD_MODE_STRIP,
    create_coordinator,
    get_coordinator,
    get_multi_coordinator,
    register_coordinator,
    register_multi_coordinator,
    resolve_build_mode,
    resolve_coordinator,
    unregister_coordinator,
    unregister_multi_coordinator,
)
from vmtools_next.core.map_art.runtime import BotRuntime
from vmtools_next.core.map_art.settings import MapArtSettings
from vmtools_next.core.map_art.store import MapArtStore
from vmtools_next.core.map_art.strip_engine import MapArtCoordinator, StripBuildLoop
from vmtools_next.core.map_art.types import (
    BotProgress,
    CellRef,
    CellResult,
    ColumnRegion,
    MapArtBuildState,
    ReconcileReport,
    Region,
    SquadAssignment,
    SquadPlan,
    SquadState,
    rel_of,
    world_of,
)

__all__ = [
    # 类型
    "Region", "ColumnRegion", "BotProgress", "MapArtBuildState",
    "SquadState", "SquadPlan", "SquadAssignment", "CellRef", "CellResult",
    "ReconcileReport", "world_of", "rel_of",
    # 纯函数
    "build_2d_matrix", "resolve_size", "partition_rectangular", "assign_supply_boxes",
    "plan_squad", "region_cells", "column_cells", "tile_ranges",
    # 基础设施
    "MapArtSettings", "MapArtStore", "ActivityLog",
    # 引擎
    "BotRuntime", "place_cell", "ensure_stand",
    "StripBuildLoop", "MapArtCoordinator",
    "ColumnBuildLoop", "MultiBotCoordinator",
    "BaseCoordinator",
    # 注册表
    "create_coordinator", "register_coordinator", "unregister_coordinator",
    "resolve_coordinator", "get_coordinator", "get_multi_coordinator",
    "register_multi_coordinator", "unregister_multi_coordinator",
    "resolve_build_mode", "BUILD_MODE_COLUMN", "BUILD_MODE_STRIP",
]
