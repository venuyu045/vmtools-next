"""Shared dataclasses used across vmtools-next.

These are the Python equivalents of the Java POJOs in VMTools-v3/data/.
They are plain data containers with no ORM or framework dependencies.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Optional


# ── Enums ────────────────────────────────────────────────────────────────

class PathingStatus(Enum):
    IDLE = auto()
    PATHING = auto()
    ARRIVED = auto()
    FAILED = auto()
    CANCELED = auto()


class PrinterStatus(Enum):
    IDLE = auto()
    BUILDING = auto()
    PAUSED = auto()
    DISABLED = auto()


class CheckResult(Enum):
    OK = auto()
    BLOCKED = auto()
    EMERGENCY_STOP = auto()


# ── Projection ───────────────────────────────────────────────────────────

@dataclass
class ProjectionInfo:
    """Metadata about a .litematic projection placement."""
    name: str = ""
    author: str = ""
    description: str = ""
    total_blocks: int = 0
    total_volume: int = 0
    size_x: int = 0
    size_y: int = 0
    size_z: int = 0
    region_count: int = 0
    region_names: list[str] = field(default_factory=list)
    # Placement origin (world coordinates, set by user)
    origin_x: int = 0
    origin_y: int = 0
    origin_z: int = 0
    file_path: str = ""


@dataclass
class ProjectionMaterialRequirement:
    """A single material type required by a projection."""
    item_id: str
    display_name: str
    count: int
    available: int = 0  # from warehouse scan
    player_has: int = 0  # from player inventory


@dataclass
class MaterialCompareResult:
    """Result of comparing projection requirements vs available materials."""
    item_id: str
    display_name: str
    required: int
    available_in_warehouse: int
    in_player_inventory: int
    shortfall: int  # required - available_in_warehouse - in_player_inventory

    @property
    def is_satisfied(self) -> bool:
        return self.shortfall <= 0


# ── Warehouse ────────────────────────────────────────────────────────────

@dataclass
class MaterialStack:
    """A stack of a single material type in a container."""
    item_id: str
    display_name: str = ""
    count: int = 0
    slot: int = -1


@dataclass
class ContainerSnapshot:
    """A point-in-time snapshot of a container's contents."""
    x: int = 0
    y: int = 0
    z: int = 0
    container_type: str = ""  # chest, barrel, shulker_box, etc.
    items: list[MaterialStack] = field(default_factory=list)
    total_items: int = 0
    scanned_at: float = 0.0  # timestamp


@dataclass
class WarehouseMaterialSnapshot:
    """Aggregated material counts across all containers in a warehouse."""
    warehouse_id: str = ""
    materials: dict[str, int] = field(default_factory=dict)  # item_id → total count
    container_count: int = 0
    scanned_at: float = 0.0


@dataclass
class WarehouseRange:
    """Defines the bounding box of a warehouse zone."""
    min_x: int = 0
    min_y: int = 0
    min_z: int = 0
    max_x: int = 0
    max_y: int = 0
    max_z: int = 0


@dataclass
class StorageZone:
    """A named zone within a warehouse."""
    zone_id: str = ""
    name: str = ""
    warehouse_id: str = ""
    range: Optional[WarehouseRange] = None
    aisle_lines: list[tuple[tuple[int, int, int], tuple[int, int, int]]] = field(default_factory=list)


# ── Travel ───────────────────────────────────────────────────────────────

@dataclass
class TravelTarget:
    """A destination for travel (pathfinding or teleport)."""
    x: int = 0
    y: int = 0
    z: int = 0
    dimension: str = "overworld"
    purpose: str = ""  # "WAREHOUSE" | "BUILD_SITE" | "DROP_POINT"
    arrival_radius: int = 3


@dataclass
class TeleportCommandTemplate:
    """A teleport command template with variable substitution."""
    template: str = "/tp {player} {x} {y} {z}"
    cooldown_seconds: float = 5.0

    def format(self, player: str, x: int, y: int, z: int) -> str:
        return self.template.format(player=player, x=x, y=y, z=z)


# ── Operation Log ────────────────────────────────────────────────────────

class OperationType(Enum):
    SCAN = "scan"
    RESTOCK = "restock"
    BUILD = "build"
    TELEPORT = "teleport"
    PATHING = "pathing"
    ERROR = "error"


@dataclass
class OperationLogEntry:
    """A single operation log entry."""
    operation_type: OperationType = OperationType.SCAN
    bot_id: str = ""
    warehouse_id: str = ""
    details: str = ""
    success: bool = True
    duration_ms: int = 0
    timestamp: float = 0.0


# ── Safety Policy ────────────────────────────────────────────────────────

@dataclass
class AutomationSafetyPolicy:
    """Safety constraints for automation operations."""
    max_ops_per_tick: int = 1
    place_interval_ticks: int = 3
    container_interact_interval: int = 10
    teleport_cooldown_seconds: int = 5
    max_pathing_distance: int = 500
    max_failures_before_stop: int = 3
    pause_on_nearby_player: bool = True
    nearby_player_radius: int = 10


# ── Server Profile ───────────────────────────────────────────────────────

@dataclass
class ServerProfile:
    """Configuration profile for a specific Minecraft server."""
    server_address: str = ""
    server_port: int = 25565
    profile_name: str = "default"
    warehouses: list[str] = field(default_factory=list)  # warehouse IDs
    teleport_commands: list[TeleportCommandTemplate] = field(default_factory=list)
    feature_flags: dict[str, bool] = field(default_factory=dict)
