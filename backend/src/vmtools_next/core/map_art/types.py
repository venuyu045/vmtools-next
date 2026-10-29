"""地图画建造 —— 领域类型（纯数据，无 IO / 无框架依赖）。

坐标铁律（全包唯一约定，2026-10-28 重构）：
  - 内存 / 矩阵 / 相对坐标一律 **0-based**：``x_rel ∈ [0, size_x-1]``、``z_rel ∈ [0, size_z-1]``
  - 世界坐标 = ``origin + 相对``：``wx = origin_x + x_rel``、``wy = origin_y``、``wz = origin_z + z_rel``
  - DB 存世界坐标；API 一律返回世界坐标
  - 列号 0-based（``column_x ∈ [0, size_x-1]``）；1-based 只允许出现在给用户看的序号里

历史背景：旧 ``multi_bot_coordinator`` 用 1-based 列号（``range(1, n+1)``）直接加 origin，
导致整幅画向 +X/+Z 偏移 1 格、第 0 列/行永远不建 —— 本次重构把该约定收敛到本文件。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

# 建造平面状态常量（progress.state）
STATE_IDLE = "idle"
STATE_MOVING = "moving"
STATE_PLACING = "placing"
STATE_RESTOCKING = "restocking"
STATE_WAITING = "waiting"      # 排尾等待 / 暂停
STATE_COMPLETED = "completed"
STATE_FAILED = "failed"
STATE_OFFLINE = "offline"

# 任务级状态（与 DB map_art_tasks.status 一致）
TASK_DRAFT = "draft"
TASK_PENDING = "pending"
TASK_RUNNING = "running"
TASK_PAUSED = "paused"
TASK_COMPLETED = "completed"
TASK_FAILED = "failed"
TASK_CANCELLED = "cancelled"


@dataclass(frozen=True)
class CellRef:
    """一个待放置格子的相对坐标 + 期望方块（不可变，可作 dict key 的一部分）。"""

    x: int
    z: int
    block_id: str

    @property
    def key(self) -> tuple[int, int]:
        return (self.x, self.z)


@dataclass
class Region:
    """矩形区域（相对坐标，含端点，0-based）——strip 模式的分区单元。"""

    x_start: int
    x_end: int
    z_start: int
    z_end: int

    @property
    def rows(self) -> int:
        return self.z_end - self.z_start + 1

    @property
    def cols(self) -> int:
        return self.x_end - self.x_start + 1

    @property
    def block_count(self) -> int:
        return self.cols * self.rows

    def contains(self, x: int, z: int) -> bool:
        return self.x_start <= x <= self.x_end and self.z_start <= z <= self.z_end

    def bounds(self) -> tuple[int, int, int, int]:
        return (self.x_start, self.x_end, self.z_start, self.z_end)


@dataclass
class ColumnRegion:
    """单列区域（相对坐标，0-based）——column 模式的工作单元。

    ``column_x`` 为 0-based 列号；``z_start`` / ``z_end`` 为 0-based 行范围（含端点）；
    ``direction`` = 1 表示沿 z+ 建造，-1 表示沿 z- 建造（排级蛇形）。
    """

    column_x: int
    z_start: int
    z_end: int
    direction: int = 1

    @property
    def block_count(self) -> int:
        return abs(self.z_end - self.z_start) + 1

    @property
    def world_x_offset(self) -> int:
        """列号 → 相对 x 偏移（0-based，直接相加即为世界 x）。"""
        return self.column_x

    def bounds(self) -> tuple[int, int, int, int]:
        lo, hi = sorted((self.z_start, self.z_end))
        return (self.column_x, self.column_x, lo, hi)

    def z_order(self) -> list[int]:
        """按建造方向排好序的行号列表。

        ⚠️ 反向排（direction=-1）时调用方传的是 ``z_start=size-1, z_end=0``，
        所以必须先取 min/max 再排序——直接 ``range(z_start, z_end+1)`` 会得到空列表
        （实测：蛇形第二排整列一格都不建）。
        """
        lo, hi = sorted((self.z_start, self.z_end))
        rng = list(range(lo, hi + 1))
        return rng if self.direction >= 0 else list(reversed(rng))


@dataclass
class BotProgress:
    """单 bot 运行时进度（内存态，不逐格落库）。"""

    bot_id: str
    state: str = STATE_IDLE
    blocks_placed: int = 0
    blocks_total: int = 0
    current_row: int = -1          # strip: 当前行；column: 当前列内行号
    last_completed_x: int = -1
    place_rate: float = 0.0        # 块/分钟（近 60s 滑动窗口）
    _recent_places: list[float] = field(default_factory=list)

    def record_place(self) -> None:
        import time as _time

        now = _time.monotonic()
        self._recent_places.append(now)
        cutoff = now - 60
        self._recent_places = [t for t in self._recent_places if t > cutoff]
        self.blocks_placed += 1
        if len(self._recent_places) > 1:
            elapsed_min = (now - self._recent_places[0]) / 60
            if elapsed_min > 0:
                self.place_rate = len(self._recent_places) / elapsed_min

    def reset(self) -> None:
        self.blocks_placed = 0
        self.place_rate = 0.0
        self._recent_places.clear()


@dataclass
class MapArtBuildState:
    """推送给前端的建造快照（Socket.IO build_progress 的载荷）。"""

    task_id: str
    status: str
    total_blocks: int
    placed_blocks: int
    bots: list[dict]
    materials: dict[str, dict]
    elapsed_sec: float
    eta_sec: float = 0.0
    net_rate: float = 0.0
    net_eta: float = 0.0
    squad_index: int = 0
    build_mode: str = "column"
    error_message: str = ""

    def to_payload(self) -> dict:
        return dict(self.__dict__)


@dataclass
class SquadAssignment:
    """一次排级编队的分配结果（列号 0-based）。"""

    bot_id: str
    column_x: int
    direction: int
    z_start: int
    z_end: int

    def to_column_region(self) -> ColumnRegion:
        return ColumnRegion(self.column_x, self.z_start, self.z_end, self.direction)


@dataclass
class SquadPlan:
    """一排的编队计划：参与 bot、列范围、方向、是否还有剩余列。"""

    squad_index: int
    direction: int
    assignments: list[SquadAssignment]
    col_start: int
    col_end: int
    total_columns: int
    total_rows: int
    remaining_columns: int = 0
    is_last: bool = False

    @property
    def active_bot_ids(self) -> list[str]:
        return [a.bot_id for a in self.assignments]


@dataclass
class SquadState:
    """编队运行时状态（协调器持有，进度落盘用）。"""

    squad_index: int = 1
    direction: int = 1
    active_bots: list[str] = field(default_factory=list)
    offline_bots: list[str] = field(default_factory=list)
    bot_columns: dict[str, int] = field(default_factory=dict)
    bot_done: set[str] = field(default_factory=set)
    total_columns: int = 0
    total_rows: int = 0
    placed_total: int = 0
    started_at: float = 0.0
    build_active_sec: float = 0.0
    last_build_ts: float = 0.0

    def to_payload(self) -> dict:
        return {
            "squad_index": self.squad_index,
            "direction": self.direction,
            "active_bots": list(self.active_bots),
            "offline_bots": list(self.offline_bots),
            "bot_columns": dict(self.bot_columns),
            "total_columns": self.total_columns,
            "total_rows": self.total_rows,
            "placed_total": self.placed_total,
        }

    def load_payload(self, data: dict) -> None:
        self.squad_index = int(data.get("squad_index", 1) or 1)
        self.direction = int(data.get("direction", 1) or 1)
        self.active_bots = list(data.get("active_bots") or [])
        self.offline_bots = list(data.get("offline_bots") or [])
        self.bot_columns = {str(k): int(v) for k, v in (data.get("bot_columns") or {}).items()}
        self.placed_total = int(data.get("placed_total", 0) or 0)
        self.total_columns = int(data.get("total_columns", 0) or 0)
        self.total_rows = int(data.get("total_rows", 0) or 0)


@dataclass
class ReconcileReport:
    """对账结果（启动 / 行尾 / 完成前 / 任务级）。"""

    label: str = ""
    checked: int = 0
    ok: int = 0
    missing: int = 0       # 读到 air（可能是 Via 数据旧，也可能是真缺口）
    wrong: int = 0         # 读到明确其它方块（放错 / 被破坏）
    unloaded: int = 0      # chunk 未加载（不判定）
    reset: int = 0         # DB 中被重置为 placed=False 的数量
    gaps: int = 0          # 进入待补清单的数量

    def merge(self, other: "ReconcileReport") -> "ReconcileReport":
        self.checked += other.checked
        self.ok += other.ok
        self.missing += other.missing
        self.wrong += other.wrong
        self.unloaded += other.unloaded
        self.reset += other.reset
        self.gaps += other.gaps
        return self

    def to_payload(self) -> dict:
        return {
            "label": self.label, "checked": self.checked, "ok": self.ok,
            "missing": self.missing, "wrong": self.wrong,
            "unloaded": self.unloaded, "reset": self.reset, "gaps": self.gaps,
        }

    def summary(self) -> str:
        parts = [f"一致 {self.ok}", f"缺失 {self.missing}", f"错色 {self.wrong}"]
        if self.reset:
            parts.append(f"重置 {self.reset}")
        if self.unloaded:
            parts.append(f"未加载 {self.unloaded}")
        return f"{self.label}：检查 {self.checked} 格 / " + " / ".join(parts)


@dataclass
class CellResult:
    """单格放置结果（两套引擎共用语义）。"""

    x_rel: int
    z_rel: int
    block_id: str
    outcome: str          # placed | verified | gap | no_material | failed | skipped
    detail: str = ""

    @property
    def ok(self) -> bool:
        return self.outcome in ("placed", "verified")

    @property
    def needs_retry(self) -> bool:
        return self.outcome in ("gap", "no_material", "failed")


def world_of(origin: tuple[int, int, int], x_rel: int, z_rel: int) -> tuple[int, int, int]:
    """相对坐标 → 世界坐标（唯一换算入口）。"""
    return (origin[0] + x_rel, origin[1], origin[2] + z_rel)


def rel_of(origin: tuple[int, int, int], wx: int, wz: int) -> tuple[int, int]:
    """世界坐标 → 相对坐标。"""
    return (wx - origin[0], wz - origin[2])
