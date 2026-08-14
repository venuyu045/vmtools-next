"""Map Art Build Coordinator — multi-bot 2D construction engine.

Orchestrates N bots building a single-layer 128×128 (or larger) map art
from a Litematica projection. Each bot gets a rectangular strip of rows
along the Z axis and runs an independent BotBuildLoop.

Key design (per implementation-plan.md Section 3):
  - Strip partition: regions split along Z, each bot covers full X [0, W-1]
  - Edge placement: bot stands z-1 (north edge), places southward
  - Independent loops: no inter-bot coordination needed (no overlapping regions)
  - Progress push: Socket.IO events every 2s or every 10 blocks placed
"""

from __future__ import annotations

import asyncio
import logging
import time
import zlib
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from vmtools_next.adapters.abstract.bot_agent import AbstractBotAgent
from vmtools_next.config import get_config
from vmtools_next.data.db import sio

logger = logging.getLogger("vmtools.map_art")


# ──────────────────────────────────────────────
# Data structures
# ──────────────────────────────────────────────

@dataclass
class Region:
    """Rectangular region assigned to one bot. Coordinates are inclusive."""
    x_start: int
    x_end: int
    z_start: int
    z_end: int

    @property
    def rows(self) -> int:
        return self.z_end - self.z_start + 1

    @property
    def block_count(self) -> int:
        return (self.x_end - self.x_start + 1) * self.rows


@dataclass
class BotProgress:
    """Per-bot runtime progress (in-memory, not DB-persisted every tick)."""
    bot_id: str
    region: Region
    state: str = "idle"           # idle|moving|placing|restocking|completed|offline
    blocks_placed: int = 0
    blocks_total: int = 0
    current_row: int = -1         # the Z-row currently being placed
    last_completed_x: int = -1    # last X placed on current row (for resume)
    place_rate: float = 0.0       # avg blocks/min
    _recent_places: list[float] = field(default_factory=list)  # timestamps for rate calc

    def record_place(self):
        now = time.monotonic()
        self._recent_places.append(now)
        # Keep last 60s
        cutoff = now - 60
        self._recent_places = [t for t in self._recent_places if t > cutoff]
        self.blocks_placed += 1
        if self._recent_places:
            elapsed_min = (now - self._recent_places[0]) / 60
            if elapsed_min > 0:
                self.place_rate = len(self._recent_places) / elapsed_min


@dataclass
class MapArtBuildState:
    """Immutable snapshot of the current build state for Socket.IO push."""
    task_id: str
    status: str
    total_blocks: int
    placed_blocks: int
    bots: list[dict]
    materials: dict[str, dict]    # item_id → {required, placed}
    elapsed_sec: float
    eta_sec: float = 0.0


# ──────────────────────────────────────────────
# Region partition
# ──────────────────────────────────────────────

def partition_rectangular(width: int, depth: int, n: int) -> list[Region]:
    """Split a W×D rectangle into N roughly equal strips along the Z axis.

    Args:
        width: X dimension (usually 128)
        depth: Z dimension (usually 128)
        n: number of bots

    Returns:
        List of Regions, each covering full width [0, width-1]
    """
    if n <= 0:
        return []
    rows_per_bot = depth // n
    remainder = depth % n
    regions = []
    z = 0
    for i in range(n):
        extra = 1 if i < remainder else 0
        h = rows_per_bot + extra
        regions.append(Region(0, width - 1, z, z + h - 1))
        z += h
    return regions


def assign_supply_boxes(
    regions: list[Region],
    origin_x: int, origin_y: int, origin_z: int,
) -> list[tuple[int, int, int]]:
    """Place a supply box at the midpoint of each region's north edge.

    y = origin_y + map_art_supply_box_y_offset（P2-8：默认 -1 把箱放地面层，
    避免悬空；config 可调）。
    Returns list of (x, y, z) for each region's supply box.
    """
    try:
        y_offset = getattr(get_config().mineflayer, "map_art_supply_box_y_offset", -1) or 0
    except Exception:
        y_offset = 0
    boxes = []
    for r in regions:
        mid_x = origin_x + (r.x_start + r.x_end) // 2
        box_z = origin_z + r.z_start - 2  # 2 blocks north of region start
        boxes.append((mid_x, origin_y + y_offset, box_z))
    return boxes


# ──────────────────────────────────────────────
# BotBuildLoop — per-bot independent build loop
# ──────────────────────────────────────────────

class BotBuildLoop:
    """Single bot's independent construction loop.

    Walks rows Z = region.z_start .. region.z_end, placing blocks
    from north edge (standing at Z-1, facing south).
    """

    # EssentialsX传送点（P2-26：从 config 读取，默认 mdssj/gzqy 保持旧行为）
    WAREHOUSE_HOME = "mdssj"
    TEMP_HOME = "gzqy"

    def __init__(
        self,
        bot_id: str,
        bot_name: str,
        task_id: str,
        region: Region,
        block_matrix: dict[tuple[int, int], str],   # (x, z) → block_id
        origin_x: int, origin_y: int, origin_z: int,
        mcp: AbstractBotAgent,
        supply_box: Optional[tuple[int, int, int]] = None,  # 分区补给箱坐标（None→用传送）
        supply_boxes: Optional[dict[str, list[tuple[int, int, int]]]] = None,  # 2026-08-14：材料→潜影盒坐标
        supply_config: Optional[dict] = None,  # 2026-08-14：{go, save, return} 三个传送指令
        food_config: Optional[dict] = None,  # 2026-08-14 模块A：食物配置
        food_boxes: Optional[list[tuple[int, int, int]]] = None,  # 2026-08-14 模块A：猪排潜影盒坐标
        on_done: Optional[callable] = None,  # 正常完成回调（coordinator 用于任务级完成判定）
        on_activity: Optional[callable] = None,  # 2026-08-14 终端：活动日志回调 (bot_id, bot_name, level, message)
    ):
        self.bot_id = bot_id
        self.bot_name = bot_name
        self.task_id = task_id
        self.region = region
        self.block_matrix = block_matrix
        self.origin_x = origin_x
        self.origin_y = origin_y
        self.origin_z = origin_z
        self.mcp = mcp

        self.progress = BotProgress(bot_id=bot_id, region=region)
        self.progress.blocks_total = region.block_count
        self._on_done = on_done
        self._on_activity = on_activity  # 2026-08-14 终端：活动日志回调

        self._paused = asyncio.Event()
        self._paused.set()     # start unpaused
        self._stopped = False
        self._current_item: Optional[str] = None  # item currently in hand
        self._current_slot: Optional[int] = None  # 当前手持快捷栏槽位（模块B：动态识别）
        self._supply_box: Optional[tuple[int, int, int]] = supply_box  # 分区补给箱坐标（None→用传送）
        # 2026-08-14：材料级潜影盒坐标（用户配置，优先级最高）+ 任务级三个传送指令
        self._supply_boxes: dict[str, list[tuple[int, int, int]]] = supply_boxes or {}
        self._supply_cfg: dict = supply_config or self._default_supply_cfg()
        # 2026-08-14 模块A：食物配置 + 猪排潜影盒坐标
        self._food_cfg: dict = food_config or self._default_food_cfg()
        self._food_boxes: list[tuple[int, int, int]] = food_boxes or []
        # 2026-08-14 模块B：快捷栏槽位 → 材料映射缓存（避免每次全背包搜索）
        self._hotbar_map: dict[int, str] = {}  # slot(0-8) → clean_item_id
        self._food_task: Optional[asyncio.Task] = None  # 食物监控协程
        # 2026-08-14：溺水/坠落防护——记录上次血量，持续下降时传送回建造点
        self._last_health: Optional[float] = None

        # P2-26：EssentialsX 传送点名从 config 读取（保持类默认值兼容）
        try:
            _mf = get_config().mineflayer
            if getattr(_mf, "map_art_warehouse_home", None):
                self.WAREHOUSE_HOME = _mf.map_art_warehouse_home
            if getattr(_mf, "map_art_temp_home", None):
                self.TEMP_HOME = _mf.map_art_temp_home
        except Exception:
            pass

        # ── 建造/寻路调参（对齐开发文档：防放错、限速、容错） ──
        # 放置间隔读 config.safety.place_interval_ticks（tick=50ms），下限 0.15s 防高频放置误判
        try:
            _ticks = getattr(get_config().safety, "place_interval_ticks", 3) or 3
            self._place_interval: float = max(0.15, int(_ticks) / 20.0)
        except Exception:
            self._place_interval: float = 0.25
        self._move_retries: int = 2             # 寻路失败重试次数
        self._place_retries: int = 3            # 放置失败重试次数
        self._move_timeout_ms: int = 20000      # 单次寻路超时
        self._place_sample_count: int = 0       # 放置采样计数（RTT 自适应）
        self._last_pos: Optional[tuple[int, int, int]] = None  # 最近一次移动到达的坐标（跳过重复寻路）

        # ── 断点续建（DB 持久化）：放置成功/已正确的方块批量写库，行完成 flush ──
        self._db_updates: list[tuple[int, int, int, str]] = []
        self._db_flushed_rows: int = 0
        # P2-9：同 run 内已验证正确的方块集合（跳过重复 get_world_block_at WS 往返）
        self._verified_set: set[tuple[int, int, int]] = set()

    # ── 蛇形寻路：偶数相对行正向（x_start→x_end），奇数行反向（x_end→x_start） ──
    #    行间只需移动 1 格（z+1，x 不变），省掉每行从 x_end 走回 x_start 的 128 格回程。
    def _row_is_forward(self, row_z: int) -> bool:
        return (row_z - self.region.z_start) % 2 == 0

    def _row_x_span(self) -> list[int]:
        """当前行 X 放置顺序（正向升序 / 反向降序）。"""
        xs = list(range(self.region.x_start, self.region.x_end + 1))
        return xs if self._row_is_forward(self.progress.current_row) else xs[::-1]

    # ── Control ──────────────────────────────

    async def pause(self):
        self._paused.clear()
        self.progress.state = "waiting"

    async def resume(self):
        self._paused.set()
        self.progress.state = "placing"

    async def stop(self):
        self._stopped = True
        self._paused.set()  # unblock so loop can exit

    # ── Main loop ────────────────────────────

    async def run(self):
        """Execute the edge-placement build loop for this bot's region."""
        logger.info("[%s] Build loop started: rows %d→%d",
                     self.bot_id, self.region.z_start, self.region.z_end)
        self._activity("info", f"开始建造区域 z[{self.region.z_start}..{self.region.z_end}]")

        # 断点续建：恢复 DB 中已放置进度（已 placed 坐标加载到 _verified_set，
        # 信任 DB 跳过重复 verify——避免 16384 块全量 WS 往返，仅「重新开始」全量核对）
        await self._restore_progress()

        # 2026-08-14 模块A：启动食物监控协程（饱食度/血量低时吃副手猪排）
        self._food_task = asyncio.create_task(self._food_monitor_loop())
        # 2026-08-14 模块B：初始化快捷栏槽位映射（避免每色首次全背包搜索）
        await self._refresh_hotbar_map()

        # 2026-08-14：保存建造点 home（/esethome dth），供寻路失败/淹死复活后
        # 用 /ehomes dth 传送回来。若 bot 当前不在建造点（如刚登录），此操作
        # 保存的是当前点——首次补货后 save 指令会覆盖为正确建造点。
        try:
            r = await self.mcp.send_chat(self._supply_cfg.get("save", "/esethomes dth"))
            if isinstance(r, dict) and r.get("success") is False:
                logger.warning("[%s] save build home failed: %s", self.bot_id, r.get("error", "?"))
            else:
                await asyncio.sleep(1.0)
                self._activity("info", "已保存建造点位置（dth）")
        except Exception as e:
            logger.warning("[%s] save build home error: %s", self.bot_id, e)

        try:
            for row_z in range(self.region.z_start, self.region.z_end + 1):
                if self._stopped:
                    break

                self.progress.current_row = row_z
                world_z = self.origin_z + row_z

                # Position bot at north edge of current row
                moved = await self._move_to_row_edge(row_z)
                if not moved and not self._stopped:
                    # 2026-08-14：行边缘寻路失败（bot 淹死复活到远处/掉落/被卡）→
                    # 传送回建造点重试一次，避免任务直接失败
                    await self._try_teleport_home("行边缘寻路失败")
                    moved = await self._move_to_row_edge(row_z)
                if not moved or self._stopped:
                    break  # 移动失败（bot 离线/不可达）→ 终止本 bot 循环

                # Place blocks in this row, grouped by color
                await self._place_row(row_z, world_z)
                if self.progress.state == "offline":
                    break  # 行内移动/放置中断 → 终止循环

            if not self._stopped:
                placed = self.progress.blocks_placed
                total = self.progress.blocks_total
                if total > 0 and placed < total:
                    # 2026-08-14 修复：循环跑完但方块未放完（补货失败/放置失败跳过）
                    # → 标记区域失败，不再误报 completed（此前 0/16384 也 completed）。
                    # 仍回调 on_done，由 coordinator 据 state 判定任务 failed。
                    self.progress.state = "failed"
                    self._activity("error", f"区域完成但未放完：{placed}/{total} 方块")
                    logger.warning("[%s] Region finished but INCOMPLETE: %d/%d blocks placed",
                                   self.bot_id, placed, total)
                else:
                    self.progress.state = "completed"
                    self._activity("info", f"区域完成：{placed} 方块")
                    logger.info("[%s] Region complete: %d blocks placed",
                                self.bot_id, placed)
                # P1-10：通知 coordinator（任务级完成判定 + DB status 更新）
                if self._on_done:
                    try:
                        self._on_done(self.bot_id)
                    except Exception as e:
                        logger.warning("[%s] on_done callback error: %s", self.bot_id, e)
        except asyncio.CancelledError:
            # CancelledError 是 BaseException（Python 3.8+），不会被 except Exception 捕获
            self.progress.state = "offline"
        except Exception as e:
            # P1-9：原代码有第二个不可达的 `except Exception`（死代码），已合并
            self.progress.state = "offline"
            logger.error("[%s] Build loop error: %s", self.bot_id, e)
        finally:
            # 取消食物监控协程（2026-08-14 模块A）
            if self._food_task:
                self._food_task.cancel()
                self._food_task = None
            # P1-9：中断/异常时 flush 残留进度（防最后几行 DB 进度丢失；行内 offline 时
            # _place_row 未执行到行尾 flush）
            if self._db_updates:
                try:
                    await self._flush_db(self.progress.current_row)
                except Exception:
                    pass

    async def _move_to_row_edge(self, row_z: int):
        """Move bot to the north edge of the given row (plan D: stand at row edge).

        Bot stands 1 block north of the row (z-1). Snake pattern: forward rows
        start at x_start (walking east), backward rows start at x_end (walking
        west) — so between rows the bot only moves 1 block (z+1, x unchanged).
        """
        xs = self._row_x_span()
        target_x = self.origin_x + (xs[0] if xs else self.region.x_start)
        target_z = self.origin_z + row_z - 1  # stand 1 block north
        # 2026-08-14 修复：bot 站立高度 = origin_y -1（地面层，与补给箱 y_offset 一致）。
        # 原用 origin_y（建造层）作站立高度 → bot 与建造层方块同层/悬空 → pathfinder
        # 无法移动（实测 bot 在 69 层悬空，前进即掉落）。max_offset 2 更宽松防最后 1 格不可达。
        ok = await self._move_to(target_x, self.origin_y - 1, target_z,
                                 max_offset=2, label=f"row {row_z} edge",
                                 timeout_ms=20000)
        if not ok:
            self.progress.state = "offline"
        return ok

    async def _move_to(self, x: int, y: int, z: int, max_offset: int = 1,
                       label: str = "", timeout_ms: int | None = None,
                       ignore_y: bool = True) -> bool:
        """Move bot to within max_offset of (x, y, z) using pathfinder.

        2026-08-14：ignore_y 默认 True——地图画建造只关心 x/z 到位（bot 会落到实际
        地面），避免站立层悬空导致 3 维 GoalNear 永远无法满足而 timeout。
        Returns True on arrival, False on failure (after retries).
        """
        await self._paused.wait()
        if self._stopped:
            return False
        self.progress.state = "moving"
        timeout = timeout_ms or self._move_timeout_ms
        for attempt in range(self._move_retries + 1):
            if self._stopped:
                return False
            try:
                result = await self.mcp.move_to(
                    x, y, z, max_offset=max_offset, timeout_ms=timeout,
                    ignore_y=ignore_y,
                )
                if result.get("success"):
                    self._last_pos = (x, y, z)
                    return True
                logger.warning("[%s] move_to %s (attempt %d/%d) failed: %s",
                               self.bot_id, label or f"({x},{y},{z})",
                               attempt + 1, self._move_retries + 1, result)
            except Exception as e:
                logger.warning("[%s] move_to %s (attempt %d/%d) error: %s",
                               self.bot_id, label or f"({x},{y},{z})",
                               attempt + 1, self._move_retries + 1, e)
            await asyncio.sleep(0.5)

        # 2026-08-14：pathfinder 全部失败（落差/悬空不可达）→ 尝试自动蹲搭搭路
        # （用手头方块搭柱/搭桥前往）。仅寻路失败才触发，避免正常建造时搭出多余方块。
        await self._paused.wait()
        if self._stopped:
            return False
        self._activity("warn", f"寻路失败，尝试蹲搭前往 ({x},{y},{z})")
        # 2026-08-14：蹲搭前置条件——背包必须有可放置方块，没有先补货（从潜影盒拿）
        if not await self._ensure_scaffold_material():
            self._activity("warn", f"背包无方块且补货失败，无法蹲搭前往 ({x},{y},{z})")
            return False
        try:
            result = await self.mcp.scaffold_to(x, y, z, timeout_ms=30000)
            if result.get("success"):
                self._last_pos = (x, y, z)
                self._activity("info", f"蹲搭到达 ({x},{y},{z})")
                return True
            logger.warning("[%s] Scaffold to (%d,%d,%d) failed: %s",
                           self.bot_id, x, y, z, result.get("error", "?"))
            self._activity("warn", f"蹲搭前往 ({x},{y},{z}) 失败")
        except Exception as e:
            logger.warning("[%s] Scaffold to (%d,%d,%d) error: %s",
                           self.bot_id, x, y, z, e)
            self._activity("warn", f"蹲搭前往 ({x},{y},{z}) 异常")
        return False

    async def _place_row(self, row_z: int, world_z: int):
        """Place all blocks in a single row, grouped by color.

        Plan D + snake: bot stands 1 block north of each target (z-1), walks
        along X (direction alternates per row), verifies the target state,
        places with retry, and persists progress to DB (row-complete flush).
        """
        await self._paused.wait()
        if self._stopped:
            return

        # Gather blocks for this row, ordered by snake direction
        x_span = self._row_x_span()
        row_blocks: dict[str, list[int]] = {}  # color → [x, ...]
        for x in x_span:
            block_id = self.block_matrix.get((x, row_z))
            if block_id and block_id != "minecraft:air":
                row_blocks.setdefault(block_id, []).append(x)

        self.progress.state = "placing"

        # Place color by color
        for block_id, x_positions in row_blocks.items():
            await self._paused.wait()
            if self._stopped:
                return

            # Switch to correct item
            await self._ensure_item_in_hand(block_id)

            for x in x_positions:
                await self._paused.wait()
                if self._stopped:
                    return

                world_x = self.origin_x + x
                # 2026-08-14 模块C：真·走一格放一格——每放置一块前精确移动到该方块
                # 正北站立点（相邻格 = 1 格移动）。原实现 threshold=2 跳格、靠
                # place_block(face=AUTO) 站桩斜放，触及范围边缘易失败且非「走一格」。
                # 2026-08-14 修复：站立高度 = origin_y -1（地面层），避免悬空/与方块同层。
                stand_z = world_z - 1
                stand_y = self.origin_y - 1
                if not await self._move_to(world_x, stand_y, stand_z,
                                           max_offset=2, label=f"({world_x},{world_z})"):
                    # 2026-08-14：放置点移动失败（可能淹死复活到远处/掉坑）→
                    # 传送回建造点重试一次，避免直接区域失败
                    if await self._try_teleport_home("放置点移动失败"):
                        if not await self._move_to(world_x, stand_y, stand_z,
                                                   max_offset=2, label=f"({world_x},{world_z})"):
                            self.progress.state = "offline"
                            return
                    else:
                        self.progress.state = "offline"
                        return

                # 2) Verify: skip if the target is already correct
                if await self._verify_block(world_x, self.origin_y, world_z, block_id):
                    self.progress.record_place()
                    self.progress.last_completed_x = x
                    self._db_updates.append((world_x, self.origin_y, world_z, block_id))
                    continue

                # 3) Place with retry + rate limiting
                if await self._place_with_retry(world_x, self.origin_y, world_z, block_id):
                    self.progress.record_place()
                    self.progress.last_completed_x = x
                    self._db_updates.append((world_x, self.origin_y, world_z, block_id))
                else:
                    # 2026-08-14 放置失败告警：连续放置失败说明材料/位置异常，
                    # 记录但不中断（由行尾/区域完成判定兜底）；累计告警交由上层处理
                    logger.warning("[%s] Place FAILED after %d retries at (%d,%d,%d) %s",
                                   self.bot_id, self._place_retries,
                                   world_x, self.origin_y, world_z, block_id)

                # 4) Rate limiting between placements (anti mis-place / anti-cheat)
                #    RTT 自适应：每 10 次放置采样一次 ping，间隔 = max(base, RTT*1.5)
                self._place_sample_count += 1
                if self._place_sample_count % 10 == 0:
                    await self._update_place_interval()
                await asyncio.sleep(self._place_interval)

        # 5) 行完成 → 批量持久化进度（断点续建）
        await self._flush_db(row_z)
        # 2026-08-14 终端：行完成埋点（低频，每行一条）
        if row_z == self.region.z_start or row_z % 10 == 0 or row_z == self.region.z_end:
            self._activity("info", f"第 {row_z} 行完成")

    def _is_near(self, x: int, y: int, z: int, threshold: float = 2.0) -> bool:
        """Check whether the bot's last known position is within `threshold` blocks."""
        if self._last_pos is None:
            return False
        lx, ly, lz = self._last_pos
        return abs(lx - x) <= threshold and abs(ly - y) <= threshold and abs(lz - z) <= threshold

    async def _update_place_interval(self) -> None:
        """RTT-adaptive rate limiting: interval = max(base, RTT*1.5), capped at 2s.

        Mirrors litematica-printer's RttReplayController: never place faster
        than one round-trip, preventing mis-placed/ghost blocks on laggy servers.
        """
        try:
            state = await self.mcp.get_player_state()
            ping_ms = state.get("ping") or 0
            if ping_ms and ping_ms > 0:
                rtt_interval = ping_ms / 1000.0 * 1.5
                if rtt_interval > self._place_interval:
                    self._place_interval = min(rtt_interval, 2.0)  # 上限 2s
                    logger.info("[%s] RTT adaptive interval → %.2fs (ping=%dms)",
                                self.bot_id, self._place_interval, ping_ms)
        except Exception:
            pass

    async def _flush_db(self, row_z: int) -> None:
        """Batch-persist placed/verified blocks to DB (breakpoint resume).

        World state is the source of truth for resume (each block is
        re-verified by _verify_block on next run); the DB is used for
        progress stats (placed_blocks / UI) and fast completion check.
        """
        if not self._db_updates:
            return
        updates = self._db_updates
        self._db_updates = []
        try:
            from vmtools_next.data.db import get_session_factory
            from vmtools_next.data.models.build_map_art import MapArtBlockState
            db = get_session_factory()()
            try:
                now = datetime.now(timezone.utc)
                for x, y, z, block_id in updates:
                    row = db.query(MapArtBlockState).filter(
                        MapArtBlockState.task_id == self.task_id,
                        MapArtBlockState.x == x,
                        MapArtBlockState.y == y,
                        MapArtBlockState.z == z,
                    ).first()
                    if row is None:
                        continue
                    row.placed = True
                    row.verified = True
                    row.actual_block = block_id.split("[")[0]
                    row.placed_by_bot = self.bot_id
                    row.placed_at = now
                    row.verified_at = now
                db.commit()
            finally:
                db.close()
            self._db_flushed_rows += 1
            if self._db_flushed_rows <= 5 or self._db_flushed_rows % 10 == 0:
                logger.info("[%s] Progress persisted: row %d (%d blocks)",
                            self.bot_id, row_z, len(updates))
        except Exception as e:
            logger.warning("[%s] DB flush failed (row %d): %s", self.bot_id, row_z, e)
            # 失败不阻断建造：世界状态仍会被 _verify_block 兜底

    async def _restore_progress(self) -> None:
        """Restore previously persisted progress from DB (breakpoint resume).

        Counts blocks already marked placed in this bot's region so the UI
        starts with the correct placed_blocks figure; actual skipping is done
        by _verify_block against world state.
        """
        try:
            from vmtools_next.data.db import get_session_factory
            from vmtools_next.data.models.build_map_art import MapArtBlockState
            db = get_session_factory()()
            try:
                count = db.query(MapArtBlockState).filter(
                    MapArtBlockState.task_id == self.task_id,
                    MapArtBlockState.placed.is_(True),
                    MapArtBlockState.x >= self.origin_x + self.region.x_start,
                    MapArtBlockState.x <= self.origin_x + self.region.x_end,
                    MapArtBlockState.z >= self.origin_z + self.region.z_start,
                    MapArtBlockState.z <= self.origin_z + self.region.z_end,
                ).count()
                if count:
                    self.progress.blocks_placed = count
                    # 2026-08-14 模块补充：断点续建信任 DB——加载已 placed 坐标到
                    # _verified_set，避免 16384 块全量 WS 往返（仅在「重新开始」时全量核对）
                    rows = db.query(
                        MapArtBlockState.x, MapArtBlockState.y, MapArtBlockState.z,
                    ).filter(
                        MapArtBlockState.task_id == self.task_id,
                        MapArtBlockState.placed.is_(True),
                        MapArtBlockState.x >= self.origin_x + self.region.x_start,
                        MapArtBlockState.x <= self.origin_x + self.region.x_end,
                        MapArtBlockState.z >= self.origin_z + self.region.z_start,
                        MapArtBlockState.z <= self.origin_z + self.region.z_end,
                    ).all()
                    for row in rows:
                        self._verified_set.add((row.x, row.y, row.z))
                    logger.info("[%s] Resumed with %d blocks already placed (%d verified)",
                                self.bot_id, count, len(rows))
            finally:
                db.close()
        except Exception as e:
            logger.warning("[%s] Progress restore failed: %s", self.bot_id, e)

    async def _verify_block(self, x: int, y: int, z: int, block_id: str) -> bool:
        """Compare world block at (x,y,z) with the expected block_id (name only).

        P2-9：已验证正确的坐标缓存到 _verified_set——同一 run 内不重复
        get_world_block_at（WS 往返）；方块变化由放置后重放兜底。
        """
        key = (x, y, z)
        if key in self._verified_set:
            return True
        try:
            result = await self.mcp.get_world_block_at(x, y, z)
            actual = (result.get("name") or "air").split("[")[0]
            expected = block_id.split("[")[0]
            if actual == expected:
                self._verified_set.add(key)
                return True
            return False
        except Exception:
            return False

    async def _place_with_retry(self, x: int, y: int, z: int, block_id: str) -> bool:
        """Place a block with retries; returns True if eventually placed."""
        for attempt in range(self._place_retries):
            await self._paused.wait()
            if self._stopped:
                return False
            try:
                # face="AUTO"：Node 侧自动选面（对齐 printer getValidSide），
                # 优先北面参考（bot 站行北缘），其次下方/南面/行内/上方——参考
                # 方块缺失时自动兜底，避免固定 face="SOUTH" 导致放置失败。
                result = await self.mcp.place_block(
                    x=x, y=y, z=z,
                    face="AUTO",
                    hand="MAIN_HAND",
                    look_at_block=False,
                )
                if result.get("success"):
                    return True
                logger.warning("[%s] Place failed at (%d,%d,%d) attempt %d/%d: %s",
                               self.bot_id, x, y, z, attempt + 1, self._place_retries, result)
            except Exception as e:
                logger.warning("[%s] Place error at (%d,%d,%d) attempt %d/%d: %s",
                               self.bot_id, x, y, z, attempt + 1, self._place_retries, e)
            await asyncio.sleep(0.5)
        return False

    async def _ensure_item_in_hand(self, block_id: str):
        """Switch hotbar to the required block type, restock if empty.

        ⚠️ 必须检查 select_hotbar_item 返回值（success:false 不会抛异常——
        WS handler 返回错误 dict，而非 reject）。原实现用 except 捕获失败
        永远不触发补货（P0 修复）。
        """
        # 2026-08-14 模块B：快捷栏动态识别 —— 先查 _hotbar_map 缓存，命中则直接切槽（零搜索），
        # 未命中才走 select_hotbar_item 全背包搜索，成功后回填缓存。
        if self._current_item == block_id:
            return
        clean_id = block_id.split("[")[0] if "[" in block_id else block_id

        # 1) 查缓存：_hotbar_map 里有 → 直接 set_quick_bar_slot（零成本）
        for slot, cached_id in self._hotbar_map.items():
            if cached_id == clean_id:
                try:
                    r = await self.mcp.set_quick_bar_slot(slot)
                    if r.get("success"):
                        self._current_item = block_id
                        self._current_slot = slot
                        return
                except Exception:
                    pass
                # 缓存失效（物品已用完/被移动）→ 从缓存清除，走搜索
                del self._hotbar_map[slot]
                break

        # 2) 缓存未命中 → 全背包搜索
        result = await self._try_select_item(clean_id, block_id)
        if result:
            return

        # select 失败 → 检查背包存量
        count = await self._check_inventory_level(block_id)
        if count > 0:
            # 有物品但装备失败（如背包满/equip 失败）→ 重试一次
            logger.warning("[%s] Equip %s failed but %d in inventory, retrying...",
                           self.bot_id, clean_id, count)
            if await self._try_select_item(clean_id, block_id):
                return
            logger.warning("[%s] Equip %s retry failed, skipping this color",
                           self.bot_id, clean_id)
            return

        # 背包中没有该物品 → 补货（优先分区补给箱，否则 传送）
        logger.info("[%s] %s 用完了，开始补货...", self.bot_id, clean_id)
        self._activity("warn", f"缺少 {clean_id}，开始补货")
        if await self._do_restock(block_id):
            # 补货后刷新 hotbar_map 并重试
            await self._refresh_hotbar_map()
            await self._try_select_item(clean_id, block_id)

    async def _try_select_item(self, clean_id: str, block_id: str) -> bool:
        """Select/equip item; returns True only if the hand now holds it."""
        try:
            result = await self.mcp.select_hotbar_item(clean_id)
            if result.get("success"):
                self._current_item = block_id
                # 2026-08-14 模块B：记录实际槽位到 hotbar_map
                slot = result.get("slot")
                if isinstance(slot, int) and 0 <= slot <= 8:
                    self._hotbar_map[slot] = clean_id
                    self._current_slot = slot
                return True
            logger.warning("[%s] select_hotbar_item %s failed: %s",
                           self.bot_id, clean_id, result.get("error", "?"))
        except Exception as e:
            logger.warning("[%s] select_hotbar_item %s error: %s",
                           self.bot_id, clean_id, e)
        return False

    async def _refresh_hotbar_map(self) -> None:
        """从 get_inventory_snapshot 重建快捷栏映射（补货后/物品移动后）。"""
        try:
            snap = await self.mcp.get_inventory_snapshot(inventory_id=0)
            items = (snap.get("data", snap)).get("items", [])
            self._hotbar_map.clear()
            for s in items:
                slot = s.get("slot")
                if isinstance(slot, int) and 0 <= slot <= 8:
                    item_id = (s.get("type", "") or "").split("[")[0]
                    if item_id:
                        self._hotbar_map[slot] = item_id
        except Exception:
            pass  # 静默失败，不影响建造

    def _activity(self, level: str, message: str) -> None:
        """记录活动日志（2026-08-14 终端：实时反馈 bot 在做什么）。

        level: info | warn | error。经 on_activity 回调推给 coordinator 汇聚后
        通过 Socket.IO 广播到前端实时日志终端。同时写 loguru（服务器 /tmp/vmtools.log
        可见，便于诊断埋点是否触发）。
        """
        try:
            if level == "error":
                logger.warning("[%s] [ACT:%s] %s", self.bot_id, level, message)
            else:
                logger.info("[%s] [ACT:%s] %s", self.bot_id, level, message)
        except Exception:
            pass
        try:
            if self._on_activity:
                self._on_activity(self.bot_id, self.bot_name, level, message)
        except Exception:
            pass

    async def _try_teleport_home(self, reason: str = "") -> bool:
        """传送回建造点（return 指令，默认 /ehomes dth）。

        2026-08-14：寻路/蹲搭失败、bot 淹死复活到远处、溺水等场景兜底——
        pathfinder 无法跨越远距离时直接用传送指令回到建造点。
        """
        try:
            cmd = self._supply_cfg.get("return", "/ehomes dth")
            if reason:
                self._activity("warn", f"{reason}，传送回建造点（{cmd}）")
            else:
                self._activity("info", f"传送回建造点（{cmd}）")
            r = await self.mcp.send_chat(cmd)
            if isinstance(r, dict) and r.get("success") is False:
                self._activity("warn", f"传送回建造点失败：{r.get('error', '?')}")
                return False
            await asyncio.sleep(2.5)
            self._last_pos = None  # 传送后位置未知，强制重新寻路
            return True
        except Exception as e:
            self._activity("warn", f"传送回建造点异常：{e}")
            return False

    def _pick_restock_material(self) -> Optional[str]:
        """选一种要补货的材料：优先已配置潜影盒的、其次当前区域需要的方块。"""
        # 1) 已配置补货潜影盒的材料（用户明确指定了坐标，最可靠）
        if self._supply_boxes:
            return next(iter(self._supply_boxes))
        # 2) 从 block_matrix 选第一个非空气方块
        for (_x, _z), bid in self.block_matrix.items():
            clean = bid.split("[")[0] if "[" in bid else bid
            if clean and clean != "minecraft:air":
                return clean
        return None

    async def _ensure_scaffold_material(self) -> bool:
        """蹲搭前确保背包有可放置方块（任务材料或常见方块）；没有则先补货。

        2026-08-14：蹲搭需要用手头的方块，背包只有食物/工具时搭不了——先补货
        （从配置的潜影盒拿任务材料）再蹲搭。
        """
        # 任务需要的材料集合（这些必然是方块）
        task_materials: set[str] = set()
        for (_x, _z), bid in self.block_matrix.items():
            clean = bid.split("[")[0] if "[" in bid else bid
            if clean and clean != "minecraft:air":
                task_materials.add(clean)
        # 常见可放置方块（即使不是任务材料也能搭路）
        common = {
            "minecraft:dirt", "minecraft:cobblestone", "minecraft:stone",
            "minecraft:gravel", "minecraft:sand", "minecraft:grass_block",
            "minecraft:cobbled_deepslate", "minecraft:oak_planks",
        }
        try:
            snap = await self.mcp.get_inventory_snapshot(inventory_id=0)
            items = (snap.get("data", snap)).get("items", [])
            for s in items:
                item_id = (s.get("type", "") or "").split("[")[0]
                if s.get("count", 0) > 0 and item_id:
                    if item_id in task_materials or item_id in common:
                        return True  # 背包有可放置方块，可直接蹲搭
        except Exception:
            pass

        # 背包无可放置方块 → 补货一种任务材料
        material = self._pick_restock_material()
        if not material:
            self._activity("warn", "背包无方块且无可补货材料，无法蹲搭")
            return False
        self._activity("warn", f"背包无方块，先补货 {material} 再蹲搭")
        if await self._do_restock(material):
            await self._refresh_hotbar_map()
            return True
        self._activity("warn", f"补货 {material} 失败，无法蹲搭")
        return False

    # ── Restocking ────────────────────────────

    async def _check_inventory_level(self, block_id: str) -> int:
        """Scan player inventory and return count of block_id."""
        clean_id = block_id.split("[")[0] if "[" in block_id else block_id
        try:
            snap = await self.mcp.get_inventory_snapshot(inventory_id=0)
            items = (snap.get("data", snap)).get("items", [])
            total = sum(
                s.get("count", 0)
                for s in items
                if (s.get("type", "") or "").split("[")[0] == clean_id
            )
            return total
        except Exception:
            return 0

    @staticmethod
    def _default_supply_cfg() -> dict:
        """任务未配置时使用全局默认三个传送指令（config.py map_art_supply_*_command）。"""
        try:
            mf = get_config().mineflayer
            return {
                "go": getattr(mf, "map_art_supply_go_command", "/ehomes mdssj") or "/ehomes mdssj",
                "save": getattr(mf, "map_art_supply_save_command", "/esethomes dth") or "/esethomes dth",
                "return": getattr(mf, "map_art_supply_return_command", "/ehomes dth") or "/ehomes dth",
            }
        except Exception:
            return {"go": "/ehomes mdssj", "save": "/esethomes dth", "return": "/ehomes dth"}

    @staticmethod
    def _default_food_cfg() -> dict:
        """食物配置默认值（2026-08-14 模块A）。"""
        try:
            mf = get_config().mineflayer
            return {
                "item_id": getattr(mf, "map_art_food_item", "minecraft:cooked_porkchop"),
                "go_command": getattr(mf, "map_art_food_go_command", "/res tp lixiangxiang.qwp"),
                "wait_after_go_ms": int(getattr(mf, "map_art_food_wait_after_go_ms", 5000)),
                "eat_threshold_food": int(getattr(mf, "map_art_eat_threshold_food", 15)),
                "eat_threshold_health": int(getattr(mf, "map_art_eat_threshold_health", 15)),
            }
        except Exception:
            return {
                "item_id": "minecraft:cooked_porkchop",
                "go_command": "/res tp lixiangxiang.qwp",
                "wait_after_go_ms": 5000,
                "eat_threshold_food": 15,
                "eat_threshold_health": 15,
            }

    async def _do_restock(self, needed_block_id: str, needed_count: int = 64) -> bool:
        """Restock the required item.

        Strategies (优先级从高到低，2026-08-14 更新)：
          0. 材料级潜影盒坐标（用户配置 map_art_supply_boxes）：暂存位置 → 传送补给点 →
             寻路到该材料潜影盒坐标打开取货 → 返回工作位置（三个指令均可自定义）
          1. 分区补给箱（_supply_box 已配置）：寻路到补给箱附近 → 打开取货 → 返回建造位置
          2. fallback EssentialsX 传送：/esethome gzqy → /ehomes mdssj → withdraw → /ehomes gzqy
        """
        self.progress.state = "restocking"
        clean_id = needed_block_id.split("[")[0] if "[" in needed_block_id else needed_block_id

        # 记录建造位置（传送补货时回程用）
        build_pos = self._last_pos

        # ── 策略 0（2026-08-14）：材料级潜影盒坐标（用户配置，优先级最高） ──
        boxes = self._supply_boxes.get(clean_id) or []
        if boxes:
            try:
                logger.info("[%s] Restock %s from configured shulker boxes (%d coords)",
                            self.bot_id, clean_id, len(boxes))
                # 1. 暂存当前位置（可自定义指令，如 /esethomes dth）
                r1 = await self.mcp.send_chat(self._supply_cfg.get("save", "/esethomes dth"))
                if isinstance(r1, dict) and r1.get("success") is False:
                    logger.warning("[%s] save command failed: %s", self.bot_id, r1.get("error", "?"))
                    return False
                self._activity("info", f"暂存当前位置（{self._supply_cfg.get('save', '/esethomes dth')}）")
                await asyncio.sleep(1.5)

                # 2. 前往补给点（可自定义指令，通常为传送，如 /ehomes mdssj）
                r2 = await self.mcp.send_chat(self._supply_cfg.get("go", "/ehomes mdssj"))
                if isinstance(r2, dict) and r2.get("success") is False:
                    logger.warning("[%s] go command failed: %s", self.bot_id, r2.get("error", "?"))
                    return False
                self._activity("info", f"传送前往仓库（{self._supply_cfg.get('go', '/ehomes mdssj')}）")
                # 传送后等待 chunk 加载（原 2.5s 不足：bot 未落地 chunk 未加载，
                # blockAt 返回空 → open_container_at 直接失败 → 误回传建造点）
                await asyncio.sleep(3.5)

                # 3. 按顺序尝试每个潜影盒坐标（先显式寻路到坐标附近触发 chunk 加载，再开箱）
                taken = False
                for bx, by, bz in boxes:
                    # 显式寻路到潜影盒附近（触发 chunk 加载 + bot 到位；max_offset=3
                    # 比 2 更宽松，避免最后 1~2 格不可达导致 20s 超时）
                    self._activity("info", f"寻路到潜影盒 ({bx},{by},{bz})")
                    moved = await self._move_to(bx, by, bz, max_offset=3,
                                                label=f"shulker({bx},{by},{bz})",
                                                timeout_ms=20000)
                    if not moved:
                        self._activity("warn", f"寻路到潜影盒 ({bx},{by},{bz}) 失败")
                        logger.warning("[%s] 寻路到潜影盒(%d,%d,%d)失败，尝试下一个",
                                       self.bot_id, bx, by, bz)
                        continue
                    try:
                        open_result = await self.mcp.open_container_at(bx, by, bz, timeout_ms=15000)
                    except Exception as e:
                        logger.warning("[%s] Open shulker at (%d,%d,%d) error: %s",
                                       self.bot_id, bx, by, bz, e)
                        continue
                    data = open_result.get("data", open_result) if isinstance(open_result, dict) else {}
                    container_id = (data or {}).get("container_id") or ""
                    if not container_id:
                        # 寻路已到位但开箱失败：可能是 chunk 尚未完全加载，等 1s 重试一次
                        logger.warning("[%s] Open shulker at (%d,%d,%d) failed: %s，等 1s 重试",
                                       self.bot_id, bx, by, bz, (data or {}).get("error", "?"))
                        await asyncio.sleep(1.0)
                        try:
                            open_result = await self.mcp.open_container_at(bx, by, bz, timeout_ms=15000)
                            data = open_result.get("data", open_result) if isinstance(open_result, dict) else {}
                            container_id = (data or {}).get("container_id") or ""
                        except Exception:
                            container_id = ""
                        if not container_id:
                            self._activity("warn", f"开箱失败（潜影盒 {bx},{by},{bz}），尝试下一个")
                            logger.warning("[%s] Shulker (%d,%d,%d) 二次开箱仍失败，尝试下一个",
                                           self.bot_id, bx, by, bz)
                            continue
                    # 2026-08-14 修复：withdraw 用 try/except 包裹——Python 端对 Node
                    # 返回 success:false 会抛 MineflayerError（而非返回 dict），原代码
                    # isinstance 判断永不命中、异常被外层 except 捕获 → 误 fallback 到
                    # 策略2 传送（"挥手瞬间被传回"的根因）。现在失败→尝试下一个坐标，
                    # 且 finally 关闭容器防泄漏。
                    try:
                        wd = await self.mcp.withdraw_container_item(clean_id, needed_count, container_id)
                    except Exception as e:
                        self._activity("warn", f"开箱后取货失败：{e}")
                        logger.warning("[%s] Withdraw %s from (%d,%d,%d) error: %s，尝试下一个坐标",
                                       self.bot_id, clean_id, bx, by, bz, e)
                        try:
                            await self.mcp.close_container(container_id)
                        except Exception:
                            pass
                        continue
                    try:
                        await self.mcp.close_container(container_id)
                    except Exception:
                        pass
                    if isinstance(wd, dict) and wd.get("success") is False:
                        logger.warning(
                            "[%s] Withdraw %s from (%d,%d,%d) failed: %s，尝试下一个坐标",
                            self.bot_id, clean_id, bx, by, bz,
                            wd.get("error", "?"))
                        continue
                    taken = True
                    logger.info("[%s] Shulker restock done: %s ×%d from (%d,%d,%d)",
                                self.bot_id, clean_id, needed_count, bx, by, bz)
                    self._activity("info", f"开箱成功，取到 {clean_id} ×{needed_count}")
                    break
                if not taken:
                    logger.warning("[%s] 所有配置潜影盒均未取到 %s（可能取空/坐标不符）", self.bot_id, clean_id)

                # 4. 返回工作位置（可自定义指令，如 /ehomes dth）
                self._activity("info", f"传送返回建造点（{self._supply_cfg.get('return', '/ehomes dth')}）")
                try:
                    await self.mcp.send_chat(self._supply_cfg.get("return", "/ehomes dth"))
                    await asyncio.sleep(1.5)
                except Exception:
                    pass
                self._last_pos = None  # 传送后位置未知，强制下次寻路
                self.progress.state = "placing"
                return taken
            except Exception as e:
                logger.warning("[%s] Shulker-box restock failed: %s, fallback to old strategy",
                               self.bot_id, e)

        # ── 策略 1：分区补给箱（无传送依赖，适合多 bot 分区） ──
        if self._supply_box is not None:
            try:
                sx, sy, sz = self._supply_box
                logger.info("[%s] Restock from supply box at (%d,%d,%d)",
                            self.bot_id, sx, sy, sz)
                if await self._move_to(sx, sy, sz, max_offset=2, label="supply box",
                                       timeout_ms=25000):
                    # radius=8：实际箱子可能不在建议坐标附近（用户放置位置有偏差）
                    scan = await self.mcp.scan_nearby_blocks(
                        radius=8, max_count=20, material_filter="chest")
                    blocks = (scan.get("data", scan)).get("blocks", [])
                    if blocks:
                        chest = blocks[0]
                        open_result = await self.mcp.open_container_at(
                            chest["x"], chest["y"], chest["z"], timeout_ms=10000)
                        data = open_result.get("data", open_result) if isinstance(open_result, dict) else {}
                        container_id = (data or {}).get("container_id") or ""
                        if not container_id:
                            logger.warning("[%s] Open supply box failed: %s，回退传送仓库",
                                           self.bot_id, (data or {}).get("error", "?"))
                            if build_pos:
                                await self._move_to(*build_pos, max_offset=2,
                                                    label="back to build pos")
                        else:
                            wd = await self.mcp.withdraw_container_item(clean_id, needed_count, container_id)
                            await self.mcp.close_container(container_id)
                            # 2026-08-14 审查修复：校验取货结果，失败不返回成功
                            # （否则 bot 继续建造但手里没物品，静默漏块）
                            if isinstance(wd, dict) and wd.get("success") is False:
                                logger.warning(
                                    "[%s] Supply-box withdraw %s failed: %s，回退传送仓库",
                                    self.bot_id, clean_id, wd.get("error", "?"))
                                # 先返回建造位置再走策略2（避免策略2把补给箱处存为临时家）
                                if build_pos:
                                    await self._move_to(*build_pos, max_offset=2,
                                                        label="back to build pos")
                            else:
                                logger.info("[%s] Supply-box restock done: %s ×%d",
                                            self.bot_id, clean_id, needed_count)
                                # 返回建造位置
                                if build_pos:
                                    await self._move_to(*build_pos, max_offset=2,
                                                        label="back to build pos")
                                self.progress.state = "placing"
                                return True
                logger.warning("[%s] Supply box unavailable, fallback to teleport",
                               self.bot_id)
            except Exception as e:
                logger.warning("[%s] Supply-box restock failed: %s, fallback to teleport",
                               self.bot_id, e)

        # ── 策略 2：EssentialsX 传送仓库 ──
        saved_pos = False
        try:
            # 1. 保存当前位置（命令失败 → 立即中止，避免位置未知继续误操作）
            logger.info("[%s] Saving position → /esethome %s", self.bot_id, self.TEMP_HOME)
            r1 = await self.mcp.send_chat(f"/esethome {self.TEMP_HOME}")
            if isinstance(r1, dict) and r1.get("success") is False:
                logger.warning("[%s] /esethome failed: %s", self.bot_id, r1.get("error", "?"))
                return False
            saved_pos = True  # 位置保存成功，finally 才允许传送回（2026-08-14 审查修复）
            await asyncio.sleep(1.5)

            # 2. 传到仓库
            logger.info("[%s] Teleporting to warehouse → /ehomes %s", self.bot_id, self.WAREHOUSE_HOME)
            r2 = await self.mcp.send_chat(f"/ehomes {self.WAREHOUSE_HOME}")
            if isinstance(r2, dict) and r2.get("success") is False:
                logger.warning("[%s] /ehomes warehouse failed: %s", self.bot_id, r2.get("error", "?"))
                return False
            await asyncio.sleep(2.5)

            # 3. 扫描附近找容器
            scan = await self.mcp.scan_nearby_blocks(radius=6, max_count=20, material_filter="chest")
            blocks = (scan.get("data", scan)).get("blocks", [])
            if not blocks:
                logger.warning("[%s] 仓库附近没找到容器", self.bot_id)
                return False

            chest = blocks[0]
            cx, cy, cz = chest["x"], chest["y"], chest["z"]

            # 4. 打开 → 取材料 → 关（2026-08-14 修复：用 container_id 而非 inventoryId）
            logger.info("[%s] Opening container at (%d,%d,%d)", self.bot_id, cx, cy, cz)
            open_result = await self.mcp.open_container_at(cx, cy, cz, timeout_ms=10000)
            data = open_result.get("data", open_result) if isinstance(open_result, dict) else {}
            container_id = (data or {}).get("container_id") or ""
            if not container_id:
                logger.warning("[%s] Open warehouse container failed: %s",
                               self.bot_id, (data or {}).get("error", "?"))
                return False

            wd = await self.mcp.withdraw_container_item(clean_id, needed_count, container_id)
            await self.mcp.close_container(container_id)
            if isinstance(wd, dict) and wd.get("success") is False:
                logger.warning("[%s] Warehouse withdraw %s failed: %s",
                               self.bot_id, clean_id, wd.get("error", "?"))
                return False

            logger.info("[%s] Restock done: %s ×%d, returning...", self.bot_id, clean_id, needed_count)
            return True

        except Exception as e:
            logger.error("[%s] Restock failed: %s", self.bot_id, e)
            return False
        finally:
            # 5. 传回建造位置（仅当位置已成功保存——/esethome 失败时传回会迷失）；
            #    try/except 防覆盖返回值
            if saved_pos:
                try:
                    await self.mcp.send_chat(f"/ehomes {self.TEMP_HOME}")
                    await asyncio.sleep(1.5)
                except Exception:
                    pass
            self._last_pos = None  # 传送后位置未知，强制下次寻路
            self.progress.state = "placing"

    # ── 食物监控 + 补货（2026-08-14 模块A）──────────────────────────────

    async def _ensure_food_offhand(self) -> bool:
        """确保副手 (slot 45) 有食物（猪排），没有则补货。

        返回 True 表示副手已有食物或补货成功，False 表示补货失败（不影响建造）。
        """
        food_item = self._food_cfg.get("item_id", "minecraft:cooked_porkchop")
        # 检查副手是否已有食物
        try:
            snap = await self.mcp.get_inventory_snapshot(inventory_id=0)
            items = (snap.get("data", snap)).get("items", [])
            for s in items:
                if s.get("slot") == 40:  # 前端归一化后副手=40
                    item_id = (s.get("type", "") or "").split("[")[0]
                    if item_id == food_item and s.get("count", 0) > 0:
                        return True
        except Exception:
            pass

        # 副手无食物 → 尝试从背包装备
        try:
            r = await self.mcp.equip_offhand(food_item)
            if r.get("success"):
                logger.info("[%s] Equipped %s to offhand from inventory", self.bot_id, food_item)
                return True
        except Exception as e:
            logger.warning("[%s] equip_offhand %s failed: %s", self.bot_id, food_item, e)

        # 背包也没有 → 食物补货
        logger.info("[%s] 猪排不足，开始食物补货...", self.bot_id)
        if await self._do_food_restock():
            return await self._ensure_food_offhand()  # 递归一次（补货后再次装备）
        return False

    async def _do_food_restock(self) -> bool:
        """去猪排仓库取猪排。

        独立于材料补货：猪排仓库指令不同（/res tp lixiangxiang.qwp），
        且指令发后需等 5s（指令自带 3s 延迟 + 2s 安全余量）才能开始寻路。
        """
        self.progress.state = "restocking"
        food_item = self._food_cfg.get("item_id", "minecraft:cooked_porkchop")
        go_cmd = self._food_cfg.get("go_command", "/res tp lixiangxiang.qwp")
        wait_ms = int(self._food_cfg.get("wait_after_go_ms", 5000))

        boxes = self._food_boxes
        if not boxes:
            logger.warning("[%s] 食物潜影盒未配置，无法补货猪排", self.bot_id)
            self.progress.state = "placing"
            return False

        try:
            # 1. 保存当前位置
            r1 = await self.mcp.send_chat(self._supply_cfg.get("save", "/esethomes dth"))
            if isinstance(r1, dict) and r1.get("success") is False:
                logger.warning("[%s] Food save command failed: %s", self.bot_id, r1.get("error", "?"))
                return False
            await asyncio.sleep(1.5)

            # 2. 前往猪排仓库（指令后等 5s 再寻路）
            logger.info("[%s] Food restock: %s → wait %ds", self.bot_id, go_cmd, wait_ms // 1000)
            self._activity("info", f"猪排不足，传送前往食物仓库（{go_cmd}）")
            r2 = await self.mcp.send_chat(go_cmd)
            if isinstance(r2, dict) and r2.get("success") is False:
                logger.warning("[%s] Food go command failed: %s", self.bot_id, r2.get("error", "?"))
                return False
            await asyncio.sleep(wait_ms / 1000.0)

            # 3. 按顺序尝试每个潜影盒坐标（先显式寻路触发 chunk 加载，再开箱）
            taken = False
            for bx, by, bz in boxes:
                # 显式寻路到潜影盒附近（触发 chunk 加载 + bot 到位）
                moved = await self._move_to(bx, by, bz, max_offset=3,
                                            label=f"food-shulker({bx},{by},{bz})",
                                            timeout_ms=20000)
                if not moved:
                    logger.warning("[%s] 寻路到食物潜影盒(%d,%d,%d)失败，尝试下一个",
                                   self.bot_id, bx, by, bz)
                    continue
                try:
                    open_result = await self.mcp.open_container_at(bx, by, bz, timeout_ms=15000)
                except Exception as e:
                    logger.warning("[%s] Open food shulker at (%d,%d,%d) error: %s",
                                   self.bot_id, bx, by, bz, e)
                    continue
                data = open_result.get("data", open_result) if isinstance(open_result, dict) else {}
                container_id = (data or {}).get("container_id") or ""
                if not container_id:
                    await asyncio.sleep(1.0)
                    try:
                        open_result = await self.mcp.open_container_at(bx, by, bz, timeout_ms=15000)
                        data = open_result.get("data", open_result) if isinstance(open_result, dict) else {}
                        container_id = (data or {}).get("container_id") or ""
                    except Exception:
                        container_id = ""
                    if not container_id:
                        logger.warning("[%s] 食物潜影盒(%d,%d,%d) 二次开箱仍失败", self.bot_id, bx, by, bz)
                        continue
                try:
                    wd = await self.mcp.withdraw_container_item(food_item, 64, container_id)
                except Exception as e:
                    logger.warning("[%s] Withdraw food %s from (%d,%d,%d) error: %s，尝试下一个坐标",
                                   self.bot_id, food_item, bx, by, bz, e)
                    try:
                        await self.mcp.close_container(container_id)
                    except Exception:
                        pass
                    continue
                try:
                    await self.mcp.close_container(container_id)
                except Exception:
                    pass
                if isinstance(wd, dict) and wd.get("success") is False:
                    continue
                taken = True
                logger.info("[%s] Food restock done: %s ×64 from (%d,%d,%d)",
                            self.bot_id, food_item, bx, by, bz)
                self._activity("info", f"取到猪排 ×64（{bx},{by},{bz}）")
                break
            if not taken:
                logger.warning("[%s] 所有食物潜影盒均未取到 %s", self.bot_id, food_item)

            # 4. 返回工作位置
            try:
                await self.mcp.send_chat(self._supply_cfg.get("return", "/ehomes dth"))
                await asyncio.sleep(1.5)
            except Exception:
                pass
            self._last_pos = None
            self.progress.state = "placing"
            return taken
        except Exception as e:
            logger.warning("[%s] Food restock failed: %s", self.bot_id, e)
            self.progress.state = "placing"
            return False

    async def _food_monitor_loop(self) -> None:
        """食物监控协程：每 2s 检查饱食度/血量，低于阈值时吃副手猪排。

        在 run 启动时创建，stop 时取消。吃食物期间不阻塞建造循环。
        """
        try:
            while not self._stopped:
                await asyncio.sleep(2)
                if self._stopped:
                    break
                try:
                    state = await self.mcp.get_player_state()
                    health = state.get("health") or 20
                    food = state.get("food") or 20
                    threshold_food = int(self._food_cfg.get("eat_threshold_food", 15))
                    threshold_health = int(self._food_cfg.get("eat_threshold_health", 15))

                    # 2026-08-14 溺水/坠落防护：血量持续下降且低（掉水淹死/虚空坠落）→
                    # 立即传送回建造点，避免死亡后复活到远处丢失位置
                    if health < 8 and self._last_health is not None and health < self._last_health:
                        self._activity("warn", f"血量持续下降（{self._last_health}→{health}），疑似溺水/坠落，传送回建造点")
                        await self._try_teleport_home("血量持续下降")
                        self._last_health = health
                        continue
                    self._last_health = health

                    if food < threshold_food or health < threshold_health:
                        self._activity("info", f"饱食度 {food}/血量 {health} 低，准备进食")
                        # 优先确保副手有食物
                        has_food = await self._ensure_food_offhand()
                        if not has_food:
                            logger.warning("[%s] 食物不足且补货失败（food=%d, health=%d）",
                                           self.bot_id, food, health)
                            continue
                        # 吃副手食物
                        try:
                            r = await self.mcp.consume_offhand()
                            if r.get("success"):
                                logger.info("[%s] Ate %s (food=%d→%d, health=%d)",
                                            self.bot_id,
                                            r.get("item", "?"),
                                            food, r.get("food", 20),
                                            r.get("health", 20))
                            else:
                                logger.warning("[%s] consume_offhand failed: %s",
                                               self.bot_id, r.get("error", "?"))
                        except Exception as e:
                            logger.warning("[%s] consume_offhand error: %s", self.bot_id, e)
                except Exception:
                    pass  # 单次检查失败不影响建造
        except asyncio.CancelledError:
            pass


# ──────────────────────────────────────────────
# MapArtCoordinator — orchestrator
# ──────────────────────────────────────────────

class MapArtCoordinator:
    """Orchestrates multi-bot map art construction.

    Lifecycle:
      1. start() → parse projection, partition regions, spawn BotBuildLoops
      2. Progress pushed every 2s via Socket.IO to room "build_{task_id}"
      3. pause() / resume() / stop() → fan out to all loops
      4. add_bot() / remove_bot() → dynamic region reassignment
    """

    def __init__(self, task_id: str, projection_data: dict,
                 origin_x: int, origin_y: int, origin_z: int):
        self.task_id = task_id
        self.projection = projection_data
        self.origin = (origin_x, origin_y, origin_z)
        self._loops: dict[str, BotBuildLoop] = {}
        self._started_at: float = 0.0
        self._progress_task: Optional[asyncio.Task] = None
        self._block_matrix: dict[tuple[int, int], str] = {}
        self._done_loops: set[str] = set()  # P1-10：正常完成的任务判定
        # 2026-08-14：区域未放完（failed）的 bot——任务级完成判定排除，置 failed
        self._failed_loops: set[str] = set()
        self._completion_notified: bool = False
        # P2-27：待接管区域队列（remove_bot 释放的未完成区域 → add_bot 分配）
        self._pending_regions: list[Region] = []
        # 2026-08-14：材料级潜影盒坐标 + 任务级三个传送指令（DB 加载，构造时读一次）
        self._supply_boxes: dict[str, list[tuple[int, int, int]]] = {}
        self._supply_config: dict = {}
        # 2026-08-14 模块A：食物配置 + 猪排潜影盒坐标（DB 加载）
        self._food_config: dict = {}
        self._food_boxes: list[tuple[int, int, int]] = []
        # 2026-08-14 终端：活动日志环形缓冲（最近 300 条，前端 join 时回放）
        self._activity_log: deque = deque(maxlen=300)
        self._load_supply_data()
        self._load_food_data()

    def _load_supply_data(self) -> None:
        """从 DB 加载任务的补货配置（任务级潜影盒 + 全局仓库合并 + 三个传送指令）。

        2026-08-14 三期：任务级 map_art_supply_boxes 优先；任务没配该材料时
        自动回退全局补货仓库（map_art_supply_warehouse）——用户在首页仓库设定的
        材料↔潜影盒映射，任何任务按需材料自动复用。
        """
        try:
            from vmtools_next.data.db import get_session_factory
            from vmtools_next.data.models.build_map_art import MapArtTask, MapArtSupplyBox, MapArtSupplyWarehouse
            import json as _json
            db = get_session_factory()()
            try:
                task = db.query(MapArtTask).filter(MapArtTask.task_id == self.task_id).first()
                if task and task.supply_config:
                    try:
                        d = _json.loads(task.supply_config)
                        if isinstance(d, dict):
                            self._supply_config = {k: d.get(k, "") for k in ("go", "save", "return")}
                    except Exception:
                        pass
                # 任务级潜影盒
                task_boxes: dict[str, list[tuple[int, int, int]]] = {}
                rows = db.query(MapArtSupplyBox).filter(
                    MapArtSupplyBox.task_id == self.task_id
                ).order_by(MapArtSupplyBox.sort_order).all()
                for r in rows:
                    task_boxes.setdefault(r.item_id, []).append((r.x, r.y, r.z))
                # 全局仓库：任务没配的材料自动回退全局
                global_boxes: dict[str, list[tuple[int, int, int]]] = {}
                g_rows = db.query(MapArtSupplyWarehouse).all()
                for g in g_rows:
                    try:
                        boxes = _json.loads(g.boxes_json or "[]")
                        global_boxes[g.item_id] = [(int(b["x"]), int(b["y"]), int(b["z"])) for b in boxes if "x" in b]
                    except Exception:
                        continue
                # 合并：任务级优先，缺的用全局（建造时自动复用）
                merged: dict[str, list[tuple[int, int, int]]] = dict(global_boxes)
                for item_id, boxes in task_boxes.items():
                    merged[item_id] = boxes
                self._supply_boxes = merged
            finally:
                db.close()
        except Exception as e:
            logger.warning("[%s] Load supply data failed: %s", self.task_id, e)

    def _load_food_data(self) -> None:
        """从 DB 加载食物配置 + 猪排潜影盒坐标（2026-08-14 模块A）。
        """
        try:
            from vmtools_next.data.db import get_session_factory
            from vmtools_next.data.models.build_map_art import MapArtTask, MapArtFoodBox
            import json as _json
            db = get_session_factory()()
            try:
                task = db.query(MapArtTask).filter(MapArtTask.task_id == self.task_id).first()
                if task and task.food_config:
                    try:
                        d = _json.loads(task.food_config)
                        if isinstance(d, dict):
                            self._food_config = d
                    except Exception:
                        pass
                # 食物潜影盒坐标
                rows = db.query(MapArtFoodBox).filter(
                    MapArtFoodBox.task_id == self.task_id
                ).order_by(MapArtFoodBox.sort_order).all()
                self._food_boxes = [(r.x, r.y, r.z) for r in rows]
            finally:
                db.close()
        except Exception as e:
            logger.warning("[%s] Load food data failed: %s", self.task_id, e)

    # ── 活动日志（2026-08-14 终端）───────────────────────────────────

    def _on_loop_activity(self, bot_id: str, bot_name: str, level: str, message: str) -> None:
        """BotBuildLoop 活动日志回调：汇聚到缓冲 + 广播到前端实时日志终端。"""
        entry = {
            "task_id": self.task_id,
            "bot_id": bot_id,
            "bot_name": bot_name,
            "level": level,
            "message": message,
            "ts": datetime.now(timezone.utc).isoformat(),
        }
        self._activity_log.append(entry)
        try:
            asyncio.create_task(sio.emit("build_log", entry, room=f"build_{self.task_id}"))
            logger.info("[%s] build_log emitted (level=%s): %s", bot_id, level, message)
        except Exception as e:
            logger.warning("[%s] build_log emit failed: %s", bot_id, e)

    def emit_log_history(self) -> None:
        """前端 join 房间时回放历史日志（同步方法，由 socket handler 调用）。"""
        if not self._activity_log:
            return
        try:
            asyncio.create_task(sio.emit(
                "build_log_history",
                {"task_id": self.task_id, "logs": list(self._activity_log)},
                room=f"build_{self.task_id}",
            ))
        except Exception:
            pass

    # ── Build 2D matrix from projection layers ──

    @classmethod
    def build_2d_matrix(cls, layers: dict[int, list[tuple[int, int, int, str]]]) -> dict[tuple[int, int], str]:
        """Flatten 3D layer blocks into a 2D (x, z) → block_id matrix.

        Map art is single-layer (y offset 0), so this is straightforward.
        """
        matrix: dict[tuple[int, int], str] = {}
        for y_offset, blocks in layers.items():
            for wx, wy, wz, block_id in blocks:
                matrix[(wx, wz)] = block_id
        return matrix

    # ── Lifecycle ─────────────────────────────

    async def start(self, bot_agents: dict[str, tuple[str, AbstractBotAgent]]):
        """Start build with N bots.

        Args:
            bot_agents: {bot_id: (bot_name, AbstractBotAgent)}
        """
        self._started_at = time.monotonic()

        # Build 2D matrix
        layers = self.projection.get("layers", {})
        self._block_matrix = self.build_2d_matrix(layers)

        # Determine map size from projection
        size_x = self.projection.get("regions", {}).get("Main", {}).get("size", {}).get("x", 128)
        size_z = self.projection.get("regions", {}).get("Main", {}).get("size", {}).get("z", 128)

        n_bots = len(bot_agents)
        if n_bots == 0:
            logger.error("[%s] No bots available", self.task_id)
            return

        # Partition
        regions = partition_rectangular(size_x, size_z, n_bots)

        # 补给箱方案（开发文档 §补给策略）：每个区域北缘中点分配一个补给箱坐标
        supply_boxes = assign_supply_boxes(
            regions, self.origin[0], self.origin[1], self.origin[2],
        )

        # P2-15：建造开始前复位 bot 手动控制状态（移动控制台遗留的方向键/视角会与
        # pathfinder 并发抢控制 → 放置位置错乱）。MCC 无 set_control_state，用 hasattr 兼容。
        for bot_id, (_name, mcp) in bot_agents.items():
            try:
                if hasattr(mcp, "cancel_pathing"):
                    await mcp.cancel_pathing()
                if hasattr(mcp, "set_control_state"):
                    for ctrl in ("forward", "back", "left", "right", "jump", "sneak", "sprint"):
                        await mcp.set_control_state(ctrl, False)
            except Exception as e:
                logger.warning("[%s] Reset control state failed: %s", bot_id, e)

        # Spawn loops
        bot_ids = list(bot_agents.keys())
        for i, bot_id in enumerate(bot_ids):
            bot_name, mcp = bot_agents[bot_id]
            loop = BotBuildLoop(
                bot_id=bot_id,
                bot_name=bot_name,
                task_id=self.task_id,
                region=regions[i],
                block_matrix=self._block_matrix,
                origin_x=self.origin[0],
                origin_y=self.origin[1],
                origin_z=self.origin[2],
                mcp=mcp,
                supply_box=supply_boxes[i] if i < len(supply_boxes) else None,
                supply_boxes=self._supply_boxes,
                supply_config=self._supply_config,
                food_config=self._food_config,
                food_boxes=self._food_boxes,
                on_done=self._on_loop_done,
                on_activity=self._on_loop_activity,
            )
            self._loops[bot_id] = loop
            asyncio.create_task(loop.run())

        # Start progress push loop
        self._progress_task = asyncio.create_task(self._push_loop())

        # Emit initial map data
        await self._emit_map_init(bot_agents, regions, size_x, size_z)

        logger.info("[%s] Build started: %d bots, %d regions",
                     self.task_id, n_bots, len(regions))

    async def pause(self):
        await asyncio.gather(*(loop.pause() for loop in self._loops.values()))

    async def resume(self):
        await asyncio.gather(*(loop.resume() for loop in self._loops.values()))

    async def stop(self):
        await asyncio.gather(*(loop.stop() for loop in self._loops.values()))
        if self._progress_task:
            self._progress_task.cancel()

    # ── Dynamic bot assignment (P2-27) ─────────

    async def add_bot(self, bot_id: str, bot_name: str,
                      mcp: AbstractBotAgent) -> Optional[Region]:
        """Assign a pending (released/unfinished) region to a new bot.

        Returns the assigned Region on success, None if no region is pending
        (all regions already assigned or finished).
        """
        if not self._pending_regions:
            logger.warning("[%s] add_bot %s: no pending region to assign",
                           self.task_id, bot_id)
            return None
        region = self._pending_regions.pop(0)

        # 复位手动控制状态（同 start，防移动控制台遗留方向键与寻路抢控制）
        try:
            if hasattr(mcp, "cancel_pathing"):
                await mcp.cancel_pathing()
            if hasattr(mcp, "set_control_state"):
                for ctrl in ("forward", "back", "left", "right", "jump", "sneak", "sprint"):
                    await mcp.set_control_state(ctrl, False)
        except Exception as e:
            logger.warning("[%s] Reset control state for %s failed: %s",
                           self.task_id, bot_id, e)

        loop = BotBuildLoop(
            bot_id=bot_id,
            bot_name=bot_name,
            task_id=self.task_id,
            region=region,
            block_matrix=self._block_matrix,
            origin_x=self.origin[0],
            origin_y=self.origin[1],
            origin_z=self.origin[2],
            mcp=mcp,
            supply_box=None,  # 新 bot 走配置潜影盒 / EssentialsX 传送补货（补给箱已按原 bot 分配）
            supply_boxes=self._supply_boxes,
            supply_config=self._supply_config,
            food_config=self._food_config,
            food_boxes=self._food_boxes,
            on_done=self._on_loop_done,
            on_activity=self._on_loop_activity,
        )
        self._loops[bot_id] = loop
        asyncio.create_task(loop.run())
        logger.info("[%s] Bot %s took over region z[%d..%d]",
                    self.task_id, bot_id, region.z_start, region.z_end)
        return region

    async def remove_bot(self, bot_id: str) -> bool:
        """Stop a bot and release its unfinished region for reassignment.

        Returns True on success, False if the bot is not running in this task.
        """
        loop = self._loops.pop(bot_id, None)
        if not loop:
            logger.warning("[%s] remove_bot %s: not running in this task",
                           self.task_id, bot_id)
            return False
        await loop.stop()
        self._done_loops.discard(bot_id)
        # 已完成区域无需接管；未完成区域进入待接管队列
        if loop.progress.state != "completed":
            self._pending_regions.append(loop.region)
            logger.info("[%s] Bot %s removed, region z[%d..%d] released for takeover",
                        self.task_id, bot_id,
                        loop.region.z_start, loop.region.z_end)
        else:
            logger.info("[%s] Bot %s removed (region already completed)",
                        self.task_id, bot_id)
        return True

    # ── Progress & Socket.IO ──────────────────

    def _on_loop_done(self, bot_id: str) -> None:
        """P1-10：单个 bot 区域结束 → 全部结束后判定任务 completed / failed（DB + 推送）。"""
        loop = self._loops.get(bot_id)
        self._done_loops.add(bot_id)
        # 2026-08-14：区域未放完（补货/放置失败）→ 记入失败集合，完成判定排除
        if loop is not None and loop.progress.state == "failed":
            self._failed_loops.add(bot_id)
        if self._completion_notified or not self._loops:
            return
        if len(self._done_loops) >= len(self._loops):
            self._completion_notified = True
            if self._failed_loops:
                # 有 bot 区域未放完 → 任务置 failed（不再误报 completed）
                logger.warning("[%s] Task marked FAILED: %d/%d regions incomplete",
                               self.task_id, len(self._failed_loops), len(self._loops))
                # 停止尚未结束的其余 loop
                for bid, lp in self._loops.items():
                    if bid not in self._done_loops:
                        try:
                            asyncio.create_task(lp.stop())
                        except Exception:
                            pass
                try:
                    from vmtools_next.data.db import get_session_factory, sio as _sio
                    from vmtools_next.data.models.build_map_art import MapArtTask
                    Session = get_session_factory()
                    db = Session()
                    try:
                        task = db.query(MapArtTask).filter(
                            MapArtTask.task_id == self.task_id).first()
                        if task and task.status == "running":
                            task.status = "failed"
                            task.error_message = (
                                f"{len(self._failed_loops)} 个 Bot 区域未完成"
                                f"（补货或放置失败，实际放置 {task.placed_blocks or 0}/{task.total_blocks or 0} 方块）")
                            task.completed_at = datetime.now(timezone.utc)
                            db.commit()
                    finally:
                        db.close()
                    asyncio.create_task(_sio.emit(
                        "build_progress",
                        {"task_id": self.task_id, "status": "failed",
                         "error_message": task.error_message},
                        room=f"build_{self.task_id}",
                    ))
                    try:
                        from vmtools_next.core.task_scheduler import get_task_scheduler
                        _sched = get_task_scheduler()
                        if _sched:
                            asyncio.create_task(_sched.broadcast_queue())
                            asyncio.create_task(_sched.schedule_once())
                    except Exception as _sched_err:
                        logger.warning("[%s] Scheduler notify failed: %s",
                                       self.task_id, _sched_err)
                except Exception as e:
                    logger.warning("[%s] Failure persist failed: %s", self.task_id, e)
                return
            logger.info("[%s] All regions complete, marking task completed", self.task_id)
            try:
                from vmtools_next.data.db import get_session_factory, sio as _sio
                from vmtools_next.data.models.build_map_art import MapArtTask
                Session = get_session_factory()
                db = Session()
                try:
                    from datetime import datetime, timezone
                    task = db.query(MapArtTask).filter(
                        MapArtTask.task_id == self.task_id).first()
                    if task and task.status == "running":
                        task.status = "completed"
                        task.completed_at = datetime.now(timezone.utc)
                        db.commit()
                finally:
                    db.close()
                asyncio.create_task(_sio.emit(
                    "build_progress",
                    {"task_id": self.task_id, "status": "completed"},
                    room=f"build_{self.task_id}",
                ))
                # 2026-08-12（实施计划阶段 2）：任务完成 → 广播队列变化 +
                # 触发调度器立即启动下一个排队任务（不等 2s 轮询）
                try:
                    from vmtools_next.core.task_scheduler import get_task_scheduler
                    _sched = get_task_scheduler()
                    if _sched:
                        asyncio.create_task(_sched.broadcast_queue())
                        asyncio.create_task(_sched.schedule_once())
                except Exception as _sched_err:
                    logger.warning("[%s] Scheduler notify failed: %s",
                                   self.task_id, _sched_err)
            except Exception as e:
                logger.warning("[%s] Completion persist failed: %s", self.task_id, e)

    async def _push_loop(self):
        """Every 2 seconds, aggregate progress and push via Socket.IO."""
        try:
            while True:
                await asyncio.sleep(2)
                try:
                    await self._push_progress()
                except Exception as e:
                    # 单次推送失败不退出循环（sio.emit 可能因无客户端/序列化失败）
                    logger.warning("[%s] Push progress failed: %s", self.task_id, e)
        except asyncio.CancelledError:
            pass

    async def _push_progress(self):
        state = self._aggregate()
        room = f"build_{self.task_id}"
        await sio.emit("build_progress", state.__dict__, room=room)

        # Bot positions（2026-08-14 模块E：优先用真实位置 = mcp.last_status（status 事件
        # 每 5s 推送 position/health/food），fallback _last_pos 寻路目标；补 health/food
        # 供前端 tooltip 展示）
        bot_data = []
        for bid, loop in self._loops.items():
            lp = loop._last_pos
            real_pos = None
            health = None
            food = None
            try:
                st = getattr(loop.mcp, "last_status", None) or {}
                if isinstance(st, dict) and st.get("position"):
                    real_pos = {
                        "x": st["position"].get("x"),
                        "y": st["position"].get("y"),
                        "z": st["position"].get("z"),
                    }
                health = st.get("health")
                food = st.get("food")
            except Exception:
                pass
            # 真实位置优先；没有则回退寻路目标
            pos = real_pos or ({"x": lp[0], "y": lp[1], "z": lp[2]} if lp else None)
            bot_data.append({
                "bot_id": bid,
                "bot_name": loop.bot_name,
                "state": loop.progress.state,
                "position": pos,
                "health": health,
                "food": food,
                "region": {
                    "x_start": loop.region.x_start,
                    "x_end": loop.region.x_end,
                    "z_start": loop.region.z_start,
                    "z_end": loop.region.z_end,
                },
                "blocks_placed": loop.progress.blocks_placed,
                "blocks_total": loop.progress.blocks_total,
                "current_row": loop.progress.current_row,
                "place_rate": loop.progress.place_rate,
            })
        await sio.emit("build_bot_status", {"task_id": self.task_id, "bots": bot_data}, room=room)

    async def _emit_map_init(self, bot_agents, regions, size_x, size_z):
        """Push initial 3D map data to connected clients."""
        room = f"build_{self.task_id}"
        blocks = [
            {"x": x, "y": self.origin[1], "z": z, "expected": bid, "placed": False}
            for (x, z), bid in self._block_matrix.items()
        ]
        bots = [
            {
                "bot_id": bid,
                "name": name,
                # 稳定颜色（2026-08-14）：改用 crc32——Python hash() 对字符串每次进程随机，
                # 重启后颜色漂移；crc32 保证同一 bot 永远同色（前端画布标记同算法）
                "color": f"#{zlib.crc32(bid.encode()) & 0xFFFFFF:06x}",
                "region": {
                    "x_start": r.x_start, "x_end": r.x_end,
                    "z_start": r.z_start, "z_end": r.z_end,
                },
                "state": "idle",
            }
            for (bid, (name, _)), r in zip(bot_agents.items(), regions)
        ]
        await sio.emit("build_map_init", {
            "task_id": self.task_id,
            "blocks": blocks,
            "bots": bots,
            "origin": {"x": self.origin[0], "y": self.origin[1], "z": self.origin[2]},
            "size": {"x": size_x, "z": size_z},
        }, room=room)

    def _aggregate(self) -> MapArtBuildState:
        total = sum(l.progress.blocks_total for l in self._loops.values())
        placed = sum(l.progress.blocks_placed for l in self._loops.values())
        elapsed = time.monotonic() - self._started_at
        rate = placed / (elapsed / 60) if elapsed > 0 else 0
        remaining = total - placed
        eta = (remaining / rate) * 60 if rate > 0 else 0
        # P1-10：全部区域完成 → 任务级 status=completed（不再硬编码 running）；
        # 2026-08-14：有区域 failed（未放完）→ status=failed；
        # 任一 loop waiting（pause 置 waiting）→ status=paused（防 socket 推送
        # 覆盖前端暂停态，导致暂停后按钮消失/错乱）
        if self._failed_loops:
            status = "failed"
        elif self._done_loops and len(self._done_loops) >= len(self._loops) and self._loops:
            status = "completed"
        elif any(l.progress.state == "waiting" for l in self._loops.values()):
            status = "paused"
        else:
            status = "running"

        bots = [{
            "bot_id": l.bot_id,
            "name": l.bot_name,
            "state": l.progress.state,
            "region": {
                "x_start": l.region.x_start, "x_end": l.region.x_end,
                "z_start": l.region.z_start, "z_end": l.region.z_end,
            },
            "placed": l.progress.blocks_placed,
            "total": l.progress.blocks_total,
            "current_row": l.progress.current_row,
            "rate": l.progress.place_rate,
        } for l in self._loops.values()]

        return MapArtBuildState(
            task_id=self.task_id,
            status=status,
            total_blocks=total,
            placed_blocks=placed,
            bots=bots,
            materials={},  # populated by API layer
            elapsed_sec=elapsed,
            eta_sec=eta,
        )


# ──────────────────────────────────────────────
# Global registry of active coordinators
# ──────────────────────────────────────────────

_active_coordinators: dict[str, MapArtCoordinator] = {}


def get_coordinator(task_id: str) -> Optional[MapArtCoordinator]:
    return _active_coordinators.get(task_id)


def register_coordinator(task_id: str, coordinator: MapArtCoordinator):
    _active_coordinators[task_id] = coordinator


def unregister_coordinator(task_id: str):
    _active_coordinators.pop(task_id, None)
