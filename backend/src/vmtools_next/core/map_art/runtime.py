"""BotRuntime —— 单个 bot 的全部建造能力（不含「按什么顺序建」）。

重构前这些能力全塞在 ``BotBuildLoop``（map_art_coordinator.py 3900 行）里，
列式引擎靠继承 + 复制启动段来复用，导致两套引擎的行为漂移。
现在：

  - ``BotRuntime``：移动 / 放置 / 校验 / 补货 / 食物 / 睡觉 / 死亡复位 / 对账 / 落库
  - ``StripBuildLoop``（strip_engine）：按行蛇形
  - ``ColumnBuildLoop``（column_engine）：按列推进

子类只需实现 4 个「工作单元」钩子：
  ``work_bounds()`` / ``work_cells()`` / ``unit_label()`` / ``resume_anchor()``

放置语义统一走 ``placement.place_cell``（唯一实现）。
"""

from __future__ import annotations

import asyncio
import functools
import logging
import time
from typing import Iterable, Optional

from vmtools_next.adapters.abstract.bot_agent import AbstractBotAgent
from vmtools_next.core.map_art.activity import ActivityLog
from vmtools_next.core.map_art.geometry import tile_ranges
from vmtools_next.core.map_art.placement import ensure_stand as _ensure_stand
from vmtools_next.core.map_art.placement import place_cell as _place_cell
from vmtools_next.core.map_art.settings import MapArtSettings
from vmtools_next.core.map_art.store import MapArtStore
from vmtools_next.core.map_art.types import (
    STATE_IDLE,
    STATE_OFFLINE,
    STATE_PLACING,
    STATE_RESTOCKING,
    STATE_WAITING,
    BotProgress,
    CellResult,
    ReconcileReport,
    Region,
)
from vmtools_next.core.map_art_restock import Need, RestockPlanner, ShulkerRestocker

logger = logging.getLogger("vmtools.map_art.runtime")


def _restock_serialized(fn):
    """串行化补货协程（并发开箱会让 mineflayer 窗口状态互相覆盖）。"""

    @functools.wraps(fn)
    async def wrapper(self, *args, **kwargs):
        async with self._restock_lock:
            return await fn(self, *args, **kwargs)

    return wrapper


class BotRuntime:
    """单 bot 建造能力基类（不含建造顺序）。"""

    WAREHOUSE_HOME = "mdssj"
    TEMP_HOME = "gzqy"

    def __init__(
        self,
        *,
        bot_id: str,
        bot_name: str,
        task_id: str,
        block_matrix: dict[tuple[int, int], str],
        origin_x: int,
        origin_y: int,
        origin_z: int,
        mcp: AbstractBotAgent,
        settings: Optional[MapArtSettings] = None,
        store: Optional[MapArtStore] = None,
        activity: Optional[ActivityLog] = None,
        supply_box: Optional[tuple[int, int, int]] = None,
        supply_boxes: Optional[dict[str, list[tuple[int, int, int]]]] = None,
        supply_config: Optional[dict] = None,
        food_config: Optional[dict] = None,
        food_boxes: Optional[list[tuple[int, int, int]]] = None,
        sleep_point: Optional[tuple[int, int, int]] = None,
        on_done: Optional[callable] = None,
        on_activity: Optional[callable] = None,
    ):
        self.bot_id = bot_id
        self.bot_name = bot_name
        self.task_id = task_id
        self.block_matrix = block_matrix
        self.origin_x = int(origin_x)
        self.origin_y = int(origin_y)
        self.origin_z = int(origin_z)
        self.mcp = mcp

        self.settings = settings or MapArtSettings.load()
        self.store = store or MapArtStore(task_id)
        self.activity = activity or ActivityLog(task_id)
        self._on_done = on_done
        self._on_activity = on_activity

        self.progress = BotProgress(bot_id=bot_id)

        # ── 控制面 ──
        self._paused = asyncio.Event()
        self._paused.set()                      # set = 运行中
        self._stopped = False
        self._stop_requested = asyncio.Event()  # 列式引擎的停止信号（strip 也统一用）
        self._restock_lock = asyncio.Lock()

        # ── 手持物品缓存 ──
        self._current_item: Optional[str] = None
        self._current_slot: Optional[int] = None
        self._hotbar_map: dict[int, str] = {}

        # ── 区域缓存（补货统计 / 近区判定）──
        self._area_bounds: Optional[tuple[float, float, float, float]] = None
        self._region_materials: Optional[dict] = None
        self._restocker: Optional[ShulkerRestocker] = None
        self._supply_box = supply_box
        self._supply_boxes: dict[str, list[tuple[int, int, int]]] = supply_boxes or {}
        self._supply_cfg: dict = supply_config or self.settings.default_supply_config()
        self._food_cfg: dict = food_config or self.settings.default_food_config()
        self._food_boxes: list[tuple[int, int, int]] = food_boxes or []
        self._y_whitelist: set[tuple[int, int]] = {(b[0], b[2]) for b in self._food_boxes}
        self._whitelist_dims: set[str] = set(self.settings.whitelist_dimensions)

        # ── 补货参数（B1 修复：最小间隔真正生效）──
        self._restock_stacks: int = self.settings.restock_stacks
        self._min_restock_interval_s: float = self.settings.min_restock_interval_s
        self._last_restock_at: float = 0.0
        self._no_gain_cycles: int = 0

        # ── 移动 / 放置参数 ──
        self._stand_y_offset: int = self.settings.stand_y_offset
        self._build_residence: str = self.settings.build_residence
        self._build_world: str = self.settings.build_world
        self._place_interval: float = self.settings.place_interval_s
        self._move_retries: int = self.settings.move_retries
        self._place_retries: int = self.settings.place_retries
        self._verify_y_tol: float = self.settings.verify_y_tol
        self._tp_retry_each: int = self.settings.tp_retry_each
        self._tp_retry_total: int = self.settings.tp_retry_total
        self._move_timeout_ms: int = self.settings.move_timeout_ms
        self._place_sample_count: int = 0
        self._last_pos: Optional[tuple[int, int, int]] = None
        self._last_move_fail_reason: str = ""

        # ── 断点 / 对账状态 ──
        self._db_updates: list[tuple[int, int, int, str]] = []
        self._db_flushed_rows: int = 0
        self._verified_set: set[tuple[int, int, int]] = set()
        self._pending_confirm: list[tuple[int, int, int, str]] = []
        self._pending_gaps: list[tuple[int, int, int, str]] = []
        self._placed_coords: set[tuple[int, int, int]] = set()
        self._reconcile_stats: dict = {"start": {}, "row": {}, "done": {}}
        self._recent_reports: list[ReconcileReport] = []

        # ── 食物 / 血量 ──
        self._food_task: Optional[asyncio.Task] = None
        self._food_restock_cooldown_s: float = self.settings.food_restock_cooldown_s
        self._food_restock_cooldown_until: float = 0.0
        self._last_health: Optional[float] = None

        # ── 睡觉 ──
        self._sleep_point: Optional[tuple[int, int, int]] = sleep_point
        self._sleep_go_command: str = self.settings.sleep_go_command
        self._sleeping: bool = False
        self._sleep_event = asyncio.Event()
        self._sleep_event.set()
        self._sleep_req = asyncio.Event()
        self._sleep_hold = asyncio.Event()
        self._sleep_task: Optional[asyncio.Task] = None
        self._sleep_night_start: int = self.settings.sleep_night_start_tick
        self._sleep_night_end: int = self.settings.sleep_night_end_tick
        self._sleep_check_interval: float = self.settings.sleep_check_interval_s
        self._sleep_min_sleep_s: float = self.settings.sleep_min_sleep_s
        self._sleep_max_wait_s: float = self.settings.sleep_max_wait_s

        # ── 死亡 / 卡滞 / 坠落（列式引擎需要的，strip 也统一具备）──
        self._guard_task: Optional[asyncio.Task] = None
        self._death_lock = asyncio.Event()
        self._death_lock.set()
        self._last_known_pos: Optional[tuple[float, float, float]] = None
        self._stuck_check_ts: float = 0.0
        self._stuck_last_pos: Optional[tuple[float, float, float]] = None
        self._stuck_count: int = 0
        self._stuck_timeout_s: float = self.settings.stuck_timeout_s
        self._death_back_timeout_s: float = self.settings.death_back_timeout_s
        self._offline_timeout_s: float = self.settings.bot_offline_timeout_s
        self._fall_threshold: int = self.settings.fall_threshold
        self._column_place_interval: float = self.settings.column_place_interval_s

        # 注册死亡事件（Node 广播 bot_death）
        try:
            mcp.on_event(self._on_bot_event)
        except Exception:
            pass

        # EssentialsX 传送点（config 可覆盖类默认）
        if self.settings.warehouse_home:
            self.WAREHOUSE_HOME = self.settings.warehouse_home
        if self.settings.temp_home:
            self.TEMP_HOME = self.settings.temp_home

    # ──────────────────────────────────────────
    # 子类必须实现：工作单元
    # ──────────────────────────────────────────

    def work_bounds(self) -> tuple[int, int, int, int]:
        """当前工作单元的相对坐标边界 (x0, x1, z0, z1)，含端点。"""
        raise NotImplementedError

    def work_cells(self) -> list[tuple[int, int, str]]:
        """当前工作单元的待放置格 [(x_rel, z_rel, block_id)]。"""
        raise NotImplementedError

    def unit_label(self) -> str:
        """工作单元的可读标签（日志用）。"""
        raise NotImplementedError

    def resume_anchor(self) -> tuple[int, int, int]:
        """复位/传送兜底时的目标点（世界坐标）。"""
        x0, x1, z0, _z1 = self.work_bounds()
        return (self.origin_x + (x0 + x1) // 2,
                self.origin_y + self._stand_y_offset,
                self.origin_z + z0 - 1)

    def status_extra(self) -> dict:
        """额外推送给前端的字段（列式引擎加 column/squad）。"""
        return {}

    # ──────────────────────────────────────────
    # 控制
    # ──────────────────────────────────────────

    async def pause(self) -> None:
        self._paused.clear()
        self.progress.state = STATE_WAITING

    async def resume(self) -> None:
        self._paused.set()
        if self.progress.state == STATE_WAITING:
            self.progress.state = STATE_PLACING

    async def stop(self) -> None:
        self._stopped = True
        self._stop_requested.set()
        self._paused.set()

    def is_stopping(self) -> bool:
        return self._stopped or self._stop_requested.is_set()

    # ──────────────────────────────────────────
    # 日志
    # ──────────────────────────────────────────

    def _activity(self, level: str, message: str) -> None:
        """写活动日志（协调器缓冲 + Socket.IO 实时终端）。"""
        if self._on_activity is not None:
            try:
                self._on_activity(self.bot_id, self.bot_name, level, message)
                return
            except Exception:
                pass
        self.activity.push(level, message, self.bot_id, self.bot_name)

    # ──────────────────────────────────────────
    # 放置（两引擎共用语义）
    # ──────────────────────────────────────────

    async def place_cell(self, x_rel: int, z_rel: int, block_id: str) -> CellResult:
        """放置一格（验证 → 选物品 → 放置 → 记账），见 placement.place_cell。"""
        return await _place_cell(self, x_rel, z_rel, block_id, label=self.unit_label())

    async def ensure_stand(self, stand: tuple[int, int, int], label: str = "") -> str:
        """移动站立点 + 脚下实体校验，返回 ok / gap / fail。"""
        return await _ensure_stand(self, stand, label or self.unit_label())

    # ──────────────────────────────────────────
    # 落库
    # ──────────────────────────────────────────

    async def flush_db(self, row_label: int | str = "") -> None:
        """把 ``_db_updates`` 批量写库（一次 executemany，替代逐块 SELECT+UPDATE）。"""
        if not self._db_updates:
            return
        updates = self._db_updates
        self._db_updates = []
        written = self.store.flush_placed(updates, self.bot_id)
        self._db_flushed_rows += 1
        if self._db_flushed_rows <= 5 or self._db_flushed_rows % 10 == 0:
            logger.info("[%s] progress persisted: %s (%d blocks)",
                        self.bot_id, row_label, written)

    # 兼容别名（历史方法名，避免子类/旧调用断链）
    async def _flush_db(self, row_z: int | str = "") -> None:
        await self.flush_db(row_z)

    # ──────────────────────────────────────────
    # 对账（统一实现，替代三份近似代码）
    # ──────────────────────────────────────────

    async def reconcile_cells(
        self,
        cells: Iterable[tuple[int, int, int, str]],
        label: str = "",
        *,
        scan: bool = True,
        allow_scan: bool = True,
    ) -> ReconcileReport:
        """对一组世界坐标格做真实世界复核。

        - 格子多（≥32）且允许 → 用 ``scan_region_blocks`` 一次往返取整片
          （未加载 chunk 返回 ``block=None`` → 计入 unloaded，**不判缺口**）
        - 否则逐格 ``get_world_block_at``
        - 读到期望 → verified；读到 air → missing + 待补；读到其它 → wrong + 待补 + 重置 DB
        """
        cell_list = [(int(x), int(y), int(z), str(b)) for x, y, z, b in cells]
        rep = ReconcileReport(label=label, checked=len(cell_list))
        if not cell_list:
            return rep

        actual_map: dict[tuple[int, int], Optional[str]] = {}
        if scan and allow_scan and len(cell_list) >= 32:
            xs = [c[0] for c in cell_list]
            zs = [c[2] for c in cell_list]
            for (x0, x1) in tile_ranges(min(xs), max(xs)):
                for (z0, z1) in tile_ranges(min(zs), max(zs)):
                    try:
                        snap = await self.mcp.scan_region_blocks(
                            x_start=x0, x_end=x1, z_start=z0, z_end=z1, y=self.origin_y)
                        blocks = (snap.get("data", snap)).get("blocks", []) \
                            if isinstance(snap, dict) else []
                        for b in blocks:
                            raw = b.get("block")
                            actual_map[(b.get("x"), b.get("z"))] = (
                                None if raw is None else str(raw).split("[")[0])
                    except Exception as e:
                        logger.warning("[%s] region scan failed (%s), fallback per-cell", self.bot_id, e)
                        actual_map = {}
                        break
                if not actual_map:
                    break

        verified: list[tuple[int, int, int]] = []
        reset: list[tuple[int, int, int]] = []
        for (wx, wy, wz, expected) in cell_list:
            if actual_map:
                if (wx, wz) not in actual_map:
                    rep.unloaded += 1        # 扫描未覆盖（chunk 未加载）→ 不判定
                    continue
                raw = actual_map[(wx, wz)]
                if raw is None:
                    rep.unloaded += 1
                    continue
                actual = self._normalize_item_id(raw)
            else:
                try:
                    v = await self.mcp.get_world_block_at(wx, wy, wz)
                    actual = self._normalize_item_id((v.get("name") or "air").split("[")[0])
                except Exception:
                    actual = "air"
            exp = self._normalize_item_id(expected)
            if actual == exp:
                rep.ok += 1
                verified.append((wx, wy, wz))
                self._verified_set.add((wx, wy, wz))
            elif actual in ("air", ""):
                rep.missing += 1
                self._pending_gaps.append((wx, wy, wz, expected))
            else:
                rep.wrong += 1
                reset.append((wx, wy, wz))
                self._pending_gaps.append((wx, wy, wz, expected))

        if verified:
            self.store.mark_verified(verified)
        if reset:
            self.store.mark_reset(reset)
            rep.reset = len(reset)
        rep.gaps = rep.missing + rep.wrong
        self._recent_reports.append(rep)
        self._recent_reports = self._recent_reports[-20:]
        return rep

    def _world_bounds(self) -> tuple[int, int, int, int]:
        x0, x1, z0, z1 = self.work_bounds()
        return (self.origin_x + x0, self.origin_x + x1,
                self.origin_z + z0, self.origin_z + z1)

    async def reconcile_start(self) -> ReconcileReport:
        """启动对账：DB 中本单元 placed=True 的格做真实复核（须在传送定位后）。"""
        rows = self.store.query_cells(self._world_bounds(), placed_only=True)
        if not rows:
            return ReconcileReport(label="启动对账")
        self._activity("info", f"启动对账：DB 已置位 {len(rows)} 块，扫描比对投影…")
        rep = await self.reconcile_cells(
            [(x, y, z, exp) for x, y, z, exp, _v in rows], "启动对账")
        self.progress.blocks_placed = rep.ok
        self._reconcile_stats["start"] = rep.to_payload()
        self._activity("info", rep.summary() +
                       (f" / {rep.unloaded} 未加载" if rep.unloaded else ""))
        return rep

    async def reconcile_unit_end(self) -> ReconcileReport:
        """行/列尾复核：只复核本单元内弱确认（pending_confirm）的格。"""
        x0, x1, z0, z1 = self._world_bounds()
        pending = [pc for pc in self._pending_confirm
                   if x0 <= pc[0] <= x1 and z0 <= pc[2] <= z1]
        if not pending:
            return ReconcileReport(label="行尾复核")
        rep = await self.reconcile_cells(pending, "行尾复核", scan=False)
        done = {pc for pc in pending if (pc[0], pc[1], pc[2]) in self._verified_set}
        self._pending_confirm = [pc for pc in self._pending_confirm if pc not in done]
        self._reconcile_stats["row"] = rep.to_payload()
        if rep.ok or rep.reset:
            self._activity("debug",
                           f"{self.unit_label()} 复核：确认 {rep.ok} / 重置 {rep.reset} / 待定 {rep.missing}")
        return rep

    async def reconcile_final(self) -> tuple[int, int]:
        """完成前对账：返回 (已确认数, 待确认数)。

        已 verified 的直接计入；未 verified 的真实复核一次。
        未确认（读到 air / 未加载）→ 不算完成（防「0/16384 也 completed」）。
        """
        rows = self.store.query_cells(self._world_bounds(), placed_only=True)
        if not rows:
            return 0, 0
        verified_rows = [(x, y, z, exp) for x, y, z, exp, v in rows if v]
        unverified_rows = [(x, y, z, exp) for x, y, z, exp, v in rows if not v]
        ok = len(verified_rows)
        pending = 0
        if unverified_rows:
            rep = await self.reconcile_cells(unverified_rows, "完成前对账")
            ok += rep.ok
            pending = rep.missing + rep.wrong + rep.unloaded
        self._reconcile_stats["done"] = {
            "ok": ok, "pending": pending,
            "total": len(rows),
        }
        if pending:
            self._activity("info",
                           f"完成前对账：确认 {ok} / 待确认 {pending}（共 {len(rows)} 块）")
        return ok, pending

    # ──────────────────────────────────────────
    # 启动序列（两引擎共用）
    # ──────────────────────────────────────────

    async def startup_sequence(self, reconcile: bool = True) -> None:
        """启动序列：监控协程 → 环境检测 → 定位 + dth → 副手食物 → 夜晚先睡 → 对账 → 填坑。

        ``reconcile=False``：列式引擎用（对账/补放由协调器任务级统一做，
        避免每台 bot 各扫一遍自己的列、也避免连接条未铺好时补放误判）。
        """
        try:
            self._food_task = asyncio.create_task(self._food_monitor_loop())
            self._sleep_task = asyncio.create_task(self._sleep_monitor_loop())
            await self._refresh_hotbar_map()
        except Exception as e:
            logger.warning("[%s] startup monitors failed: %s", self.bot_id, e)

        try:
            await self._check_build_environment()
        except Exception as e:
            logger.warning("[%s] env check failed: %s", self.bot_id, e)

        try:
            await self.startup_positioning()
        except Exception as e:
            logger.warning("[%s] startup positioning failed: %s", self.bot_id, e)

        # 副手猪排
        try:
            if await self._ensure_food_offhand():
                self._activity("debug", "副手已就绪（猪排）")
            else:
                self._activity("warn", "启动时副手未就绪，建造中由食物监控兜底")
        except Exception as e:
            logger.warning("[%s] startup offhand check failed: %s", self.bot_id, e)

        # 夜晚/雷暴 → 先睡觉
        try:
            st = await self.mcp.get_time_status()
            if st.get("success"):
                tod = st.get("time_of_day")
                dim = st.get("dimension") or "unknown"
                in_win = tod is not None and self._sleep_night_start <= tod <= self._sleep_night_end
                thunder = bool(st.get("is_raining")) and int(st.get("thunder_state") or 0) > 0
                if self._sleep_point and dim in ("overworld", "minecraft:overworld", "minecraft_overworld") \
                        and (in_win or thunder) and not bool(st.get("is_sleeping")):
                    self._activity("info", f"启动时检测到夜晚（timeOfDay={tod}），先睡觉跳过黑夜")
                    try:
                        await self._do_sleep_cycle()
                    except Exception as e:
                        logger.warning("[%s] startup sleep failed: %s", self.bot_id, e)
        except Exception as e:
            logger.warning("[%s] startup night check failed: %s", self.bot_id, e)

        if not reconcile:
            self._activity("info", f"启动序列完成（{self.unit_label()}，对账由协调器统一执行）")
            return

        # 对账（须在传送定位后：chunk 已加载才准）→ 填坑 → 复对账
        try:
            await self.reconcile_start()
            if self._pending_gaps:
                self._activity("info", f"启动填坑：对账发现 {len(self._pending_gaps)} 格缺口，先补放")
                filled = await self._fill_pending_gaps()
                if filled > 0:
                    self._activity("info", f"启动填坑完成：补放 {filled} 格")
                    try:
                        await self.reconcile_start()
                    except Exception:
                        pass
        except Exception as e:
            logger.warning("[%s] startup reconcile failed: %s", self.bot_id, e)

        self._activity("info", f"启动序列完成（{self.unit_label()}）")

    async def startup_positioning(self) -> bool:
        """启动定位 + dth 覆盖（仅到位才覆盖，防旧任务坐标污染 dth）。"""
        placed0 = False
        try:
            fixed0 = (self._supply_cfg.get("return_fixed") or "/ehomes mapart").strip()
            if fixed0:
                self._activity("info", f"启动定位：传送回固定建造点（{fixed0}）")
                if await self._send_teleport(fixed0):
                    placed0 = (await self._verify_at_build_area()) is None
            if not placed0 and self.origin_x is not None:
                tp = f"/tp {self.origin_x} {self.origin_y + self._stand_y_offset} {self.origin_z}"
                self._activity("info", f"固定点不在本任务区域，改用任务 origin 传送（{tp}）")
                try:
                    if await self._send_teleport(tp):
                        placed0 = (await self._verify_at_build_area()) is None
                except Exception as e:
                    logger.warning("[%s] origin tp failed: %s", self.bot_id, e)
            if not placed0:
                gx, gy, gz = self.resume_anchor()
                self._activity("info", f"定位到工作单元起点（{gx},{gy},{gz}）")
                placed0 = await self._move_to(gx, gy, gz, max_offset=2,
                                              label="initial position", timeout_ms=30000,
                                              allow_scaffold=True, verify_height=True)
                if not placed0:
                    await self._try_teleport_home("启动定位失败")
                    placed0 = await self._move_to(gx, gy, gz, max_offset=2,
                                                  label="initial position retry",
                                                  timeout_ms=30000,
                                                  allow_scaffold=True, verify_height=True)
            if placed0:
                await self.save_dth("启动定位到位")
            elif self.origin_x is not None:
                tp = f"/tp {self.origin_x} {self.origin_y + self._stand_y_offset} {self.origin_z}"
                self._activity("warn", f"启动定位失败，改用任务 origin 传送后保存 dth（{tp}）")
                try:
                    if await self._send_teleport(tp) and (await self._verify_at_build_area()) is None:
                        placed0 = True
                        await self.save_dth("origin /tp 到位")
                    else:
                        self._activity("warn", "origin 传送未到位，dth 保持原值")
                except Exception:
                    self._activity("warn", "origin 传送异常，dth 保持原值")
        except Exception as e:
            logger.warning("[%s] startup positioning error: %s", self.bot_id, e)
        return placed0

    async def save_dth(self, label: str) -> None:
        """保存临时传送点（dth）。"""
        try:
            r = await self.mcp.send_chat(self._supply_cfg.get("save", "/esethomes dth"))
            if isinstance(r, dict) and r.get("success") is False:
                logger.warning("[%s] save build home failed: %s", self.bot_id, r.get("error", "?"))
            else:
                await asyncio.sleep(1.0)
                self._activity("info", f"已保存建造点位置（dth）· {label}")
        except Exception as e:
            logger.warning("[%s] save build home error: %s", self.bot_id, e)

    # ──────────────────────────────────────────
    # 卡滞 / 坠落监控
    # ──────────────────────────────────────────

    async def guard_monitor_loop(self) -> None:
        """卡滞 / 坠落监控（2s 轮询）。

        卡滞判据必须结合「动作进展」：bot 放置时本来就站着不动，
        只看位置会把正常放置误判成卡滞（2026-08-19 教训）。
        """
        try:
            last_placed = -1
            while not self.is_stopping():
                await asyncio.sleep(2)
                if self.is_stopping():
                    break
                if self.progress.state not in ("moving", "placing"):
                    self._stuck_count = 0
                    continue
                try:
                    p = await self._get_player_pos_full()
                    if not p:
                        continue
                    now = time.monotonic()
                    placed_now = self.progress.blocks_placed
                    has_progress = last_placed >= 0 and placed_now > last_placed
                    last_placed = placed_now
                    if self._stuck_last_pos is None:
                        self._stuck_last_pos = p
                        self._stuck_check_ts = now
                    else:
                        moved = max(abs(p[0] - self._stuck_last_pos[0]),
                                    abs(p[2] - self._stuck_last_pos[2]))
                        if has_progress:
                            self._stuck_last_pos = p
                            self._stuck_check_ts = now
                            self._stuck_count = 0
                        elif moved < 0.2 and (now - self._stuck_check_ts) >= self._stuck_timeout_s:
                            self._stuck_count += 1
                            self._activity("warn",
                                           f"卡滞：{self._stuck_timeout_s:.0f}s 无位置/放置进展"
                                           f"（第 {self._stuck_count} 次）")
                            if self._stuck_count >= 3:
                                self._activity("error", "连续 3 次卡滞 → 标记离线")
                                self.progress.state = STATE_OFFLINE
                                self._notify_offline("stuck_3x")
                                break
                            await self.recover_from_stuck()
                            self._stuck_last_pos = None
                            self._stuck_check_ts = 0
                        elif moved >= 0.2:
                            self._stuck_last_pos = p
                            self._stuck_check_ts = now

                    if p[1] < (self.origin_y + self._stand_y_offset - self._fall_threshold):
                        self._activity("warn",
                                       f"检测到坠落（y={p[1]:.1f}），尝试传送自救")
                        try:
                            await self._try_teleport_home("坠落自救")
                        except Exception as e:
                            logger.warning("[%s] fall rescue failed: %s", self.bot_id, e)
                        self._stuck_last_pos = None
                        self._stuck_check_ts = 0
                except Exception as e:
                    logger.warning("[%s] guard monitor error: %s", self.bot_id, e)
        except asyncio.CancelledError:
            pass

    async def recover_from_stuck(self) -> None:
        """卡滞恢复：传送到本单元最近的已完成格续建。"""
        target = None
        for (x_rel, z_rel, _bid) in self.work_cells():
            wx, wz = self.origin_x + x_rel, self.origin_z + z_rel
            if (wx, self.origin_y, wz) in self._placed_coords:
                target = (wx, wz)
        if target is None:
            self._activity("warn", "本单元无已完成格，传送回建造点")
            await self._try_teleport_home("卡滞无完成格")
            return
        self._activity("info", f"卡滞恢复：传送至最近完成格 ({target[0]},{target[1]})")
        await self._move_to(target[0], self.origin_y + 1, target[1],
                            max_offset=1, label="stuck-recover", verify_height=True)

    def _notify_offline(self, reason: str) -> None:
        """上报离线（列式协调器据此减员重组；strip 忽略）。"""
        cb = getattr(self, "_on_bot_offline", None)
        if cb:
            try:
                cb(self.bot_id, reason)
            except Exception:
                pass

    # ──────────────────────────────────────────
    # 死亡复位（增强版，两引擎共用）
    # ──────────────────────────────────────────

    async def handle_death(self) -> None:
        """死亡复位：/back 主流程 + 移动锁定轮询 + 降级链 + 拾取掉落。"""
        try:
            death_pos = self._last_known_pos
            self._activity("warn", f"死亡事件：死亡点 {death_pos}，等待复活")
            await asyncio.sleep(5)
            if self.is_stopping():
                return
            y_threshold = self.origin_y - 9
            if death_pos and death_pos[1] >= y_threshold:
                self._activity("info", "死亡点位于建造层附近，执行 /back")
                self._death_lock.clear()
                try:
                    await self.mcp.send_chat("/back")
                    deadline = time.monotonic() + self._death_back_timeout_s
                    ok = False
                    while time.monotonic() < deadline:
                        await asyncio.sleep(0.5)
                        p = await self._get_player_pos_full()
                        if p and max(abs(p[0] - death_pos[0]), abs(p[2] - death_pos[2])) <= 2 \
                                and abs(p[1] - self.origin_y) <= 1.5:
                            ok = True
                            break
                    if not ok:
                        self._activity("warn", "/back 超时未到位，进入降级链")
                        await self.death_fallback_chain()
                        return
                    self._activity("info", "/back 到位，解锁移动")
                except Exception as e:
                    logger.warning("[%s] /back failed: %s", self.bot_id, e)
                    await self.death_fallback_chain()
                    return
                finally:
                    self._death_lock.set()
                try:
                    await self.pickup_drops(death_pos)
                except Exception as e:
                    logger.warning("[%s] pickup drops failed: %s", self.bot_id, e)
            else:
                self._activity("warn", f"死亡点 {death_pos} 不在建造层，直接降级链")
                await self.death_fallback_chain()
                return
            try:
                await self._ensure_food_offhand()
            except Exception as e:
                logger.warning("[%s] death food check failed: %s", self.bot_id, e)
            self._activity("info", "死亡复位完成，从断点续建")
        except Exception as e:
            logger.warning("[%s] death handling error: %s", self.bot_id, e)
            await self.death_fallback_chain()

    async def death_fallback_chain(self) -> None:
        """复位降级链：dth → 固定点 → origin /tp → 上报离线。"""
        self._activity("warn", "进入复位降级链")
        try:
            if await self._send_teleport(self._supply_cfg.get("return", "/ehomes dth")) \
                    and (await self._verify_at_build_area()) is None:
                self._activity("info", "降级链一级（dth）成功")
                return
        except Exception as e:
            logger.warning("[%s] fallback L1 failed: %s", self.bot_id, e)
        try:
            if await self._send_teleport(self._supply_cfg.get("return_fixed", "/ehomes mapart")) \
                    and (await self._verify_at_build_area()) is None:
                self._activity("info", "降级链二级（固定点）成功")
                await self.recover_from_stuck()
                return
        except Exception as e:
            logger.warning("[%s] fallback L2 failed: %s", self.bot_id, e)
        try:
            tp = f"/tp {self.origin_x} {self.origin_y + self._stand_y_offset} {self.origin_z}"
            if await self._send_teleport(tp) and (await self._verify_at_build_area()) is None:
                self._activity("info", "降级链三级（任务 origin）成功")
                return
        except Exception as e:
            logger.warning("[%s] fallback L3 failed: %s", self.bot_id, e)
        self._activity("error", "复位降级链全部失败 → 离线待援")
        self.progress.state = STATE_OFFLINE
        self._notify_offline("death_fallback_failed")

    async def pickup_drops(self, at: tuple[float, float, float]) -> None:
        """走到死亡点拾取掉落物。"""
        try:
            p = await self._get_player_pos_full()
            if p and max(abs(p[0] - at[0]), abs(p[2] - at[2])) > 2:
                await self._move_to(int(round(at[0])), int(round(at[1])) + 1,
                                    int(round(at[2])), max_offset=2,
                                    label="pickup-drops", verify_height=False)
            await asyncio.sleep(1.5)
        except Exception as e:
            logger.warning("[%s] pickup drops failed: %s", self.bot_id, e)

    def _on_bot_event(self, event_name: str, data: dict) -> None:
        """Node 事件回调（同步契约：mineflayer_client 不 await handler）。"""
        try:
            if event_name != "bot_death":
                return
            if self.is_stopping():
                self._activity("debug", "任务已停止，忽略 bot 死亡恢复")
                return
            try:
                st = getattr(self.mcp, "last_status", None) or {}
                if isinstance(st, dict) and st.get("position"):
                    self._last_known_pos = (
                        float(st["position"].get("x", 0)),
                        float(st["position"].get("y", 0)),
                        float(st["position"].get("z", 0)),
                    )
            except Exception:
                pass
            self._activity("warn", "⚠️ bot 死亡——等待复活后执行 /back 复位")
            logger.warning("[%s] bot_death received, scheduling recovery", self.bot_id)
            asyncio.create_task(self.handle_death())
        except Exception as e:
            logger.warning("[%s] bot event handler error: %s", self.bot_id, e)

    # ──────────────────────────────────────────
    # 状态上报
    # ──────────────────────────────────────────

    def bot_status(self) -> dict:
        """推送用的 bot 状态（含真实位置/血量/饱食 + 引擎附加字段）。"""
        real_pos = None
        health = None
        food = None
        try:
            st = getattr(self.mcp, "last_status", None) or {}
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
        lp = self._last_pos
        pos = real_pos or ({"x": lp[0], "y": lp[1], "z": lp[2]} if lp else None)
        data = {
            "bot_id": self.bot_id,
            "bot_name": self.bot_name,
            "state": self.progress.state,
            "position": pos,
            "health": health,
            "food": food,
            "blocks_placed": self.progress.blocks_placed,
            "blocks_total": self.progress.blocks_total,
            "current_row": self.progress.current_row,
            "place_rate": self.progress.place_rate,
            "rate": self.progress.place_rate,
            # 前端兼容别名（A1：旧模板读 placed/total）
            "placed": self.progress.blocks_placed,
            "total": self.progress.blocks_total,
        }
        try:
            data.update(self.status_extra() or {})
        except Exception:
            pass
        return data

    def reconcile_snapshot(self) -> dict:
        return dict(self._reconcile_stats)

    # ──────────────────────────────────────────
    # 子类清理钩子
    # ──────────────────────────────────────────

    async def cleanup_tasks(self) -> None:
        """收尾：取消监控协程 + flush 残留进度。"""
        for attr in ("_guard_task", "_food_task", "_sleep_task"):
            task = getattr(self, attr, None)
            if task is not None:
                try:
                    task.cancel()
                except Exception:
                    pass
                setattr(self, attr, None)
        self._sleeping = False
        self._sleep_event.set()
        self._sleep_req.clear()
        self._sleep_hold.clear()
        if self._db_updates:
            try:
                await self.flush_db(self.unit_label())
            except Exception:
                pass


# ──────────────────────────────────────────────
# 能力实现（移动 / 放置 / 补货 / 食物 / 睡觉 —— 自旧 BotBuildLoop 原样迁入）
# ──────────────────────────────────────────────

    async def _move_to(self, x: int, y: int, z: int, max_offset: int = 1,
                       label: str = "", timeout_ms: int | None = None,
                       ignore_y: bool = True, allow_scaffold: bool = True,
                       verify_height: bool = False) -> bool:
        """Move bot to within max_offset of (x, y, z) using pathfinder.

        2026-08-14：ignore_y 默认 True——地图画建造只关心 x/z 到位（bot 会落到实际
        地面），避免站立层悬空导致 3 维 GoalNear 永远无法满足而 timeout。
        allow_scaffold：补货/传送链路的内部寻路传 False——仓库内寻路失败时不应再
        触发蹲搭（蹲搭→背包无方块→又补货→又寻路，递归死循环），直接失败返回即可。
        2026-08-15 修复（verify_height）：GoalNearXZ（ignore_y）不校验 y——bot 掉下
        平台（如 y=57 vs 站立层 68）时 x/z 到位也"成功"，导致放置时 blockAt 全空气
        （chunk 未加载）→ 参考全失效。建造侧移动传 verify_height=True：到位后检查
        bot 实际 y 与目标 y 偏差，超差（>4）视为未真正到位（返回 False 触发传送兜底）。
        Returns True on arrival, False on failure (after retries).
        """
        await self._paused.wait()
        if self._stopped:
            return False
        self.progress.state = "moving"
        # 2026-08-15：寻路前确保目标站立点安全——站立点有水/岩浆时用背包方块填掉，
        # 避免 pathfinder 到达后 bot 站进水里（用户实测"寻路到水里面"）。填水失败
        # 不阻塞寻路（由后续溺水分级防护/传送兜底处理）。
        try:
            es = await self.mcp.ensure_standable(x, y, z)
            if isinstance(es, dict):
                if es.get("note"):
                    self._activity("debug", f"站立点检查：{es['note']}")
                elif es.get("success") is False and es.get("need_block"):
                    self._activity("warn", f"目标站立点需垫方块但背包无方块：{es.get('error', '?')}")
        except Exception:
            pass
        timeout = timeout_ms or self._move_timeout_ms
        self._last_move_fail_reason = ""  # 2026-08-16 P0-4：每次调用重置失败原因标签
        for attempt in range(self._move_retries + 1):
            if self._stopped:
                return False
            try:
                # 2026-08-15 P1：优先 baritone 移植寻路（A* + Moves，支持爬升/跳跃/
                # 下降，寻路天然校验站立面——平台边缘无方块不会走）。失败回退旧 pathfinder。
                # 2026-08-16 P1-2：双寻路 max_offset 语义统一（不再对 baritone 放宽到 2）——
                # 行内精确站立（max_offset=1）必须同格，宽放会导致 bot 停在错误格放置。
                result = await self.mcp.baritone_move(
                    x, y, z, max_offset=max_offset, timeout_ms=timeout)
                if not result.get("success"):
                    _bt_reason = str(result.get("reason") or "")
                    self._activity(
                        "debug",
                        f"baritone 寻路失败（{_bt_reason}），回退旧 pathfinder")
                    result = await self.mcp.move_to(
                        x, y, z, max_offset=max_offset, timeout_ms=timeout,
                        ignore_y=ignore_y,
                    )
                if result.get("success"):
                    if verify_height:
                        # 2026-08-16 P1-3：高度校验改为「y 偏差 + 脚下实体」双条件——
                        #   · y 偏差 ≤ map_art_verify_y_tol（默认 1.0）：容忍浮点/半砖/台阶抖动
                        #     （原硬编码 0.6 过严，bot 行进中微抖即误判未到位 → 频繁传送兜底）；
                        #   · 脚下必须实体（air/water/lava = 悬空/掉水，无论如何判未到位）——
                        #     这是防坠落的核心强条件，不受 y 容差放宽影响。
                        # 失败时写入 self._last_move_fail_reason 供 P0-4 兜底分流。
                        try:
                            st = await self.mcp.get_player_state()
                            d2 = st.get("data", st) if isinstance(st, dict) else {}
                            loc = d2.get("location") or {}
                            by = loc.get("y")
                            if isinstance(by, (int, float)):
                                dy = abs(float(by) - y)
                                # 脚下实体检查（强条件）
                                foot = await self.mcp.get_world_block_at(
                                    int(round(loc.get("x", x))), int(by) - 1,
                                    int(round(loc.get("z", z))))
                                foot_name = ((foot.get("name") or "air")
                                             .split("[")[0])
                                if foot_name in ("air", "water", "lava",
                                                 "flowing_water", "flowing_lava"):
                                    # 2026-08-16 修复：Via 不推送 blockUpdate，客户端
                                    # world 可能读到旧 air（服务器实际有方块；bot 重启后
                                    # forceLocalBlock 本地标记丢失）→ 不能只看本地方块。
                                    # 结合 on_ground（服务器真实物理状态）判断：
                                    #   on_ground=True → 客户端数据旧，容忍通过；
                                    #   on_ground=False → 真悬空/掉水，判未到位（防坠落）。
                                    on_ground = d2.get("is_on_ground")
                                    if on_ground is True:
                                        self._activity(
                                            "debug",
                                            f"脚下客户端读 {foot_name} 但 on_ground=true"
                                            f"（Via 数据旧），容忍通过")
                                    else:
                                        self._last_move_fail_reason = "fall"
                                        self._activity(
                                            "warn",
                                            f"移动到位但脚下是 {foot_name} 且未落地"
                                            f"（bot 悬空/掉水）——判定未到位")
                                        return False
                                if dy > self._verify_y_tol:
                                    # 2026-08-16 用户反馈：bot「移动到位却高度不符」但
                                    # 实际站的位置是对的——根因是 bot 不在建造区时（如
                                    # 异步食物补货去仓库 y≈57），主循环仍以建造层 y=69
                                    # 校验高度 → 误判。改为：先查 bot 是否在建造区附近，
                                    # 不在 → 不报"高度不符"，交上层传送兜底拉回（防坠落
                                    # 强条件仍是脚下实体检查，不受影响）。
                                    try:
                                        bx2 = float(loc.get("x", x))
                                        bz2 = float(loc.get("z", z))
                                        if not self._near_build_area(bx2, bz2):
                                            self._last_move_fail_reason = "away"
                                            self._activity(
                                                "debug",
                                                f"移动到位但 bot 不在建造区附近"
                                                f"（{bx2:.0f},{bz2:.0f}，目标y={y}实际y={by:.1f}），"
                                                f"交上层传送兜底")
                                            return False
                                    except Exception:
                                        pass
                                    self._last_move_fail_reason = "height"
                                    self._activity(
                                        "warn",
                                        f"移动到位但高度不符（目标y={y}，实际y={by:.1f}，"
                                        f"容差{self._verify_y_tol}）——bot 可能掉下/不在站立层")
                                    return False
                                if dy > 0.5:
                                    self._activity(
                                        "debug",
                                        f"到位高度偏差 {dy:.2f} 格但脚下实体，容忍通过")
                        except Exception:
                            pass
                    self._last_pos = (x, y, z)
                    return True
                _reason = str(result.get("reason") or "unknown")
                if not self._last_move_fail_reason:
                    self._last_move_fail_reason = _reason.split(":")[0].strip()
                logger.warning("[%s] move_to %s (attempt %d/%d) failed: %s",
                               self.bot_id, label or f"({x},{y},{z})",
                               attempt + 1, self._move_retries + 1, result)
            except Exception as e:
                if not self._last_move_fail_reason:
                    self._last_move_fail_reason = "error"
                logger.warning("[%s] move_to %s (attempt %d/%d) error: %s",
                               self.bot_id, label or f"({x},{y},{z})",
                               attempt + 1, self._move_retries + 1, e)
            await asyncio.sleep(0.5)

        # 2026-08-14：pathfinder 全部失败（落差/悬空不可达）→ 尝试自动蹲搭搭路
        # （用手头方块搭柱/搭桥前往）。仅寻路失败且允许蹲搭才触发（补货内寻路
        # allow_scaffold=False，避免"寻路→蹲搭→无方块→补货→再寻路"递归死循环）。
        if not allow_scaffold:
            self._activity("debug", f"寻路到 ({x},{y},{z}) 失败（补货链路内，不触发蹲搭）")
            return False
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

    async def _fill_pending_gaps(self) -> int:
        """补放破洞（2026-08-16 用户需求，2026-08-18 按用户期望流程重构）：

        流程（对齐用户描述）：
          1) 【最近空洞优先】：按 bot 当前位置距离排序，逐个补齐；
          2) 【寻路到旁边实体方块】：站立点优先 bot 当前位置（on_ground=true 且同层
             相邻），否则 4 方向相邻格【直接寻路尝试】——baritone/_move_to_step 成功
             即视为可达且脚下实体（不再依赖读本地方块判断，Via 数据旧不再误跳过）；
          3) 补完一个空洞后若还有空洞 → 继续下一格（bot 逐格移动，天然靠近后续空洞）；
          4) 材料不足/不可达/放置失败 → 保留在清单（下次续建兜底），不阻塞。
        返回成功补放格数。
        """
        if not self._pending_gaps:
            return 0
        filled = 0
        remaining: list[tuple[int, int, int, str]] = []
        # 1. 最近空洞优先（按 bot 当前位置切比雪夫距离排序）
        try:
            _ps0 = await self.mcp.get_player_state()
            _pd0 = _ps0.get("data", _ps0) if isinstance(_ps0, dict) else {}
            _loc0 = _pd0.get("location") or {}
            _bx0, _bz0 = _loc0.get("x"), _loc0.get("z")
            if _bx0 is not None and _bz0 is not None:
                self._pending_gaps.sort(
                    key=lambda g: max(abs(float(_bx0) - g[0]), abs(float(_bz0) - g[2])))
        except Exception:
            pass
        self._activity("info",
                       f"开始补放破洞（共 {len(self._pending_gaps)} 格，最近优先）")
        for wx, wy, wz, block_id in self._pending_gaps:
            if self._stopped:
                remaining.append((wx, wy, wz, block_id))
                continue
            # 2026-08-16 用户需求（睡觉不被填坑阻塞）：夜晚睡觉请求到达 → 暂停填坑去
            # 睡觉（睡完 set _sleep_event 继续填）。否则填坑 59 格耗时长，夜晚一直
            # 不睡 → bot 被骷髅/怪物打死（实测）。
            if self._sleep_req.is_set():
                self._sleep_req.clear()
                self._sleep_event.clear()
                self._sleep_hold.set()
                await self._sleep_event.wait()  # 睡觉完成恢复
            try:
                # 已放（对账/并发补过）→ 跳过
                if await self._verify_block(wx, wy, wz, block_id):
                    filled += 1
                    continue
                # ── 找可站立格（2026-08-18 双路径）──
                stand: Optional[tuple[int, int, int]] = None
                # 路径1：bot 当前真实位置兜底（Via 数据旧时本地方块读取不可靠）——
                # bot 已在建造区且 on_ground=true、与缺口同层相邻 → 直接用当前位置。
                try:
                    _ps = await self.mcp.get_player_state()
                    _pd = _ps.get("data", _ps) if isinstance(_ps, dict) else {}
                    if _pd.get("is_on_ground") is True:
                        _loc = _pd.get("location") or {}
                        _bx, _by, _bz = _loc.get("x"), _loc.get("y"), _loc.get("z")
                        if _bx is not None and _by is not None and _bz is not None:
                            _bxi, _bzi = int(round(_bx)), int(round(_bz))
                            if max(abs(_bxi - wx), abs(_bzi - wz)) <= 2 \
                                    and abs(float(_by) - wy) <= 1.5:
                                stand = (_bxi, int(round(float(_by))), _bzi)
                                self._activity("debug",
                                               f"补放 {wx},{wz}：用 bot 当前位置 "
                                               f"({_bxi},{int(round(float(_by)))},{_bzi}) 站立（on_ground 兜底）")
                except Exception:
                    pass
                # 路径2：4 方向相邻格【直接寻路尝试】——不再读本地方块判断脚下实体
                #（Via 数据旧读到 air 会误跳过），改为：寻路成功 = 站立点可达且脚下
                # 实体（baritone 不会把 bot 送到悬空格），失败换下一方向。
                if stand is None:
                    for sx, sz in ((wx, wz - 1), (wx - 1, wz), (wx + 1, wz), (wx, wz + 1)):
                        mv = await self._move_to_step(sx, wy, sz,
                                                      label=f"gap-stand({wx},{wz})")
                        if mv is True:
                            stand = (sx, wy, sz)
                            break
                if stand is None:
                    remaining.append((wx, wy, wz, block_id))
                    continue
                if not await self._ensure_item_in_hand(block_id):
                    remaining.append((wx, wy, wz, block_id))
                    continue
                if await self._place_with_retry(wx, wy, wz, block_id):
                    self.progress.record_place()
                    self._db_updates.append((wx, wy, wz, block_id))
                    self._placed_coords.add((wx, wy, wz))
                    filled += 1
                else:
                    remaining.append((wx, wy, wz, block_id))
                await asyncio.sleep(self._place_interval)
            except Exception as e:
                logger.warning("[%s] Gap fill (%d,%d,%d) error: %s",
                               self.bot_id, wx, wy, wz, e)
                remaining.append((wx, wy, wz, block_id))
        self._pending_gaps = remaining
        if filled and self._db_updates:
            try:
                await self.flush_db(self.progress.current_row)
            except Exception:
                pass
        self._activity("info", f"补放破洞完成：成功 {filled} 格，剩余 {len(remaining)} 格")
        return filled

    async def _stand_solid(self, x: int, y: int, z: int) -> bool:
        """站立格前提校验（P0-2）：bot 站立点 (x, y, z) 脚下 (x, y-1, z) 必须是实体方块。

        非实体（air/water/lava）→ 返回 False（悬空/掉水），调用方跳过放置并记待补，
        不触发传送兜底（区别于移动到位后的脚下检查——那是防坠落强条件）。

        ⚠️ 2026-08-16 修复：Via 不推送 blockUpdate，客户端 world 读到旧 air（服务器
        实际有方块；bot 重启后 forceLocalBlock 本地标记丢失）→ 单看本地方块会把
        bot 真站在方块上误判为"脚下非实体"→ 每格都跳过（卡死，placed 停滞）。
        结合 on_ground（服务器真实物理状态）：on_ground=true → 数据旧容忍；
        false → 真悬空/掉水才判不满足（保持防坠落）。
        """
        try:
            foot = await self.mcp.get_world_block_at(int(x), int(y) - 1, int(z))
            name = ((foot.get("name") or "air").split("[")[0])
            if name not in ("air", "water", "lava", "flowing_water", "flowing_lava"):
                return True
            # 客户端读 air/水：结合服务器物理状态判断
            try:
                _st = await self.mcp.get_player_state()
                _d2 = _st.get("data", _st) if isinstance(_st, dict) else {}
                if _d2.get("is_on_ground") is True:
                    return True  # Via 数据旧，bot 实际站在方块上
            except Exception:
                pass
            return False
        except Exception:
            return False  # 读取失败按不满足处理（安全侧）

    async def _move_to_step(self, x: int, y: int, z: int, label: str = "") -> bool:
        """轻量行内移动（P0-2/P0-1）：距离 ≤3 用 walk_toward 控制键直走（带护栏，
        Node 侧校验目标格脚下实体 + 此处校验 y 偏差，非实体/高度不符拒绝直走防踩空）；
        失败/超距离回退 _move_to。

        返回值：
          True = 到位；False = 失败（调用方传送兜底/重试）；
          "gap" = 目标站立点脚下非实体（上一格未放成功/缺块）——直接跳过该格，
                  不回退 baritone（回退只会反复掉水→传送死循环→区域 failed）。
        """
        try:
            p = await self._get_player_pos_full()
            if p:
                d = max(abs(p[0] - x), abs(p[2] - z))
                if d <= 3.0:
                    try:
                        r = await self.mcp.walk_toward(x=x, z=z, timeout_ms=8000)
                        if r.get("success"):
                            # walk_toward 只移动 x/z：校验 bot 实际高度与目标站立层
                            # 一致（防 bot 掉下平台后 x/z 到位但高度错误继续放置）
                            p2 = await self._get_player_pos_full()
                            if p2 and abs(float(p2[2]) - y) > 1.5:
                                self._last_move_fail_reason = "height"
                                self._activity("debug",
                                               f"直走到位但高度不符（目标y={y}，实际y={p2[2]:.1f}），回退寻路")
                                return await self._move_to(x, y, z, max_offset=1,
                                                           label=label or f"step({x},{z})",
                                                           verify_height=True)
                            return True
                        # 2026-08-16：walk_toward 失败——目标是【脚下非实体】（缺块/悬空）
                        # → 直接跳过该格（gap），不回退 baritone（防掉水死循环）。
                        _why = str(r.get("reason") or "")
                        if _why in ("unsafe_foot", "foot_check_error"):
                            self._last_move_fail_reason = "gap"
                            self._activity("debug",
                                           f"walk_toward 目标脚下非实体（{_why}）→ 跳过该格 ({x},{z})")
                            return "gap"
                    except Exception:
                        pass
            return await self._move_to(x, y, z, max_offset=1,
                                       label=label or f"step({x},{z})",
                                       verify_height=True)
        except Exception:
            return await self._move_to(x, y, z, max_offset=1,
                                       label=label or f"step({x},{z})",
                                       verify_height=True)

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

    async def _verify_block(self, x: int, y: int, z: int, block_id: str) -> bool:
        """Compare world block at (x,y,z) with the expected block_id (name only).

        P2-9：已验证正确的坐标缓存到 _verified_set——同一 run 内不重复
        get_world_block_at（WS 往返）；方块变化由放置后重放兜底。
        ⚠️ 2026-08-15 P3 修正：不信任缓存直接跳过——方块可能被破坏（打掉），
        必须每次真实读取世界比对，发现"已放但被打掉"→返回 False →重放。
        （16384 格 × 本地 WS 读取开销可接受，换来环境感知正确性）
        """
        key = (x, y, z)
        try:
            result = await self.mcp.get_world_block_at(x, y, z)
            # 2026-08-16 修复：get_world_block_at 返回 name 无前缀（如 black_concrete），
            # 而 block_id 带 minecraft: 前缀 → 直接 == 永远不相等 → 放置成功却被判
            # WRONG 重试（本轮实测 "Place confirmed WRONG: got black_concrete want
            # minecraft:black_concrete" 的根因）。统一 _normalize_item_id 比较。
            actual = self._normalize_item_id((result.get("name") or "air").split("[")[0])
            expected = self._normalize_item_id(block_id)
            if actual == expected:
                self._verified_set.add(key)
                return True
            if key in self._verified_set:
                # 2026-08-15 P3：缓存说已放但世界实际不对（被破坏）→ 清除缓存并重放
                self._verified_set.discard(key)
            return False
        except Exception:
            return False

    async def _place_with_retry(self, x: int, y: int, z: int, block_id: str) -> bool:
        """Place a block with retries; returns True if eventually placed (弱确认成功).

        2026-08-16 P0-5 放置后校验分层（防进度虚高）：
          - 强确认：放置后 world 读到期望方块（服务器真实或本地 forceLocalBlock 同步，
            两者在重启对账时收敛）→ verified；
          - 放错：world 读到明确的非期望、非 air 方块 → 重试（attempt 内）；
          - 弱确认：world 读到 air/读取失败（Via 不推送块更新，客户端数据旧）→
            信任 place_block 发出（服务器已接受），坐标记入 _pending_confirm，
            由行尾复核（_reconcile_row）/启动对账收敛 verified，防止进度虚高。
        """
        # 2026-08-16 修复：统一 _normalize_item_id 比较（get_world_block_at 返回
        # name 无前缀，block_id 带 minecraft: 前缀，直接 == 永远不相等 → 放置成功
        # 却被判 WRONG 重试，进度不记录、方块漏计）。
        expected = self._normalize_item_id(block_id)
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
                    trust_down=True,  # 2026-08-15 P3：地图画目标下方是平台，
                    # 客户端 blockAt 可能读旧 air → 信任服务器直接以目标下方为参考放置
                )
                if result.get("success"):
                    # P0-3 防线：放置返回的手持物品必须与期望一致（防止放错方块）
                    pw = result.get("placed_with") or ""
                    if pw and self._normalize_item_id(pw) != self._normalize_item_id(expected):
                        logger.warning(
                            "[%s] Place used WRONG item at (%d,%d,%d): held %s want %s — abort",
                            self.bot_id, x, y, z, pw, expected)
                        return False  # 已发出错误放置，由上层跳过/待补（对账会修正）
                    # P0-5 放置后确认（分层）
                    try:
                        v = await self.mcp.get_world_block_at(x, y, z)
                        actual = self._normalize_item_id((v.get("name") or "air").split("[")[0])
                        if actual == expected:
                            # 强确认（服务器真实或本地已同步）
                            self._verified_set.add((x, y, z))
                            return True
                        if actual in ("air", ""):
                            # 弱确认：客户端数据旧（服务器已放置但本地未同步）→ 记入待确认
                            self._pending_confirm.append((x, y, z, block_id))
                            return True
                        logger.warning(
                            "[%s] Place confirmed WRONG at (%d,%d,%d): got %s want %s — retry",
                            self.bot_id, x, y, z, actual, expected)
                    except Exception:
                        # 读取失败（chunk 未加载等）→ 弱确认（避免死循环）
                        self._pending_confirm.append((x, y, z, block_id))
                        return True
                logger.warning("[%s] Place failed at (%d,%d,%d) attempt %d/%d: %s",
                               self.bot_id, x, y, z, attempt + 1, self._place_retries, result)
            except Exception as e:
                logger.warning("[%s] Place error at (%d,%d,%d) attempt %d/%d: %s",
                               self.bot_id, x, y, z, attempt + 1, self._place_retries, e)
            await asyncio.sleep(0.5)
        return False

    async def _ensure_item_in_hand(self, block_id: str) -> bool:
        """Switch hotbar to the required block type, restock if empty.

        ⚠️ 必须检查 select_hotbar_item 返回值（success:false 不会抛异常——
        WS handler 返回错误 dict，而非 reject）。原实现用 except 捕获失败
        永远不触发补货（P0 修复）。
        2026-08-16 P0-3：返回 bool —— True=手持已就绪；False=无法获取该材料
        （补货也失败/装备失败），调用方跳过放置，杜绝手持错误物品放错方块。
        """
        # 2026-08-14 模块B：快捷栏动态识别 —— 先查 _hotbar_map 缓存，命中则直接切槽（零搜索），
        # 未命中才走 select_hotbar_item 全背包搜索，成功后回填缓存。
        if self._current_item == block_id:
            # ⚠️ 2026-08-16 修复：_current_item 缓存可能失效（手持被服务器/补货/
            # 掉落等操作改变）——直接返回 True 会导致手持错误物品放置（实测
            # "Place used WRONG item: held light_gray_concrete want black_concrete"）。
            # 缓存命中时用 get_player_state.held_item（服务器真实手持）快速校验，
            # 不一致 → 缓存失效 → 走下方 select 流程。
            try:
                _st = await self.mcp.get_player_state()
                _d2 = _st.get("data", _st) if isinstance(_st, dict) else {}
                _held = _d2.get("held_item") or ""
                if not _held:
                    # 手持空（切换中/物品消耗完）→ 不信任缓存，走下方 select 流程
                    # （否则 place 时 No item in hand 连续失败）
                    self._current_item = None
                elif self._normalize_item_id(_held) != self._normalize_item_id(block_id):
                    self._activity("debug",
                                   f"手持缓存失效（实际 {_held}，期望 {block_id}）→ 重新选择")
                    self._current_item = None
                else:
                    return True
            except Exception:
                return True  # 读取失败容忍（保持原行为）
        clean_id = block_id.split("[")[0] if "[" in block_id else block_id

        # 1) 查缓存：_hotbar_map 里有 → 直接 set_quick_bar_slot（零成本）
        # 2026-08-14 修复：缓存存归一化 ID，比较也归一化（原带前缀 vs 无前缀永不命中）
        norm_id = self._normalize_item_id(clean_id)
        for slot, cached_id in self._hotbar_map.items():
            if cached_id == norm_id:
                try:
                    r = await self.mcp.set_quick_bar_slot(slot)
                    if r.get("success"):
                        # ⚠️ 2026-08-16：Via 下 set_quick_bar_slot 后客户端 heldItem
                        # 可能延迟更新，且 hotbar_map 槽位内容可能已过期（如补货/背包
                        # 变化后旧槽位变成 cyan）→ 等 0.5s 后验证实际手持，不符则
                        # 缓存失效，走下方 select 全背包搜索（防手持错误物品放置）。
                        await asyncio.sleep(0.5)
                        try:
                            _st2 = await self.mcp.get_player_state()
                            _d2b = _st2.get("data", _st2) if isinstance(_st2, dict) else {}
                            _held2 = _d2b.get("held_item") or ""
                            if not _held2 or self._normalize_item_id(_held2) != norm_id:
                                self._activity("debug",
                                               f"hotbar_map 槽位 {slot} 内容过期（实际 {_held2 or '空'}，期望 {clean_id}）→ 缓存失效")
                                del self._hotbar_map[slot]
                                break
                        except Exception:
                            pass  # 读取失败不拦截
                        self._current_item = block_id
                        self._current_slot = slot
                        return True
                except Exception:
                    pass
                # 缓存失效（物品已用完/被移动）→ 从缓存清除，走搜索
                del self._hotbar_map[slot]
                break

        # 2) 缓存未命中 → 全背包搜索
        if await self._try_select_item(clean_id, block_id):
            return True

        # select 失败 → 检查背包存量
        count = await self._check_inventory_level(block_id)
        if count > 0:
            # 有物品但装备失败（如背包满/equip 失败）→ 重试一次
            logger.warning("[%s] Equip %s failed but %d in inventory, retrying...",
                           self.bot_id, clean_id, count)
            if await self._try_select_item(clean_id, block_id):
                return True
            logger.warning("[%s] Equip %s retry failed, skipping this color",
                           self.bot_id, clean_id)
            return False

        # 2026-08-18 用户反馈（材料不缺仍补货→数量超64）：背包检测到 0 时
        # 【二次确认】——Via 下 get_inventory_snapshot 可能读到旧数据/窗口残留
        # 返回 0（实际背包有货），单次读取误判"无货"→ 补货 → 原有货 + 新取 64 超量。
        # 间隔 0.5s 重读一次，仍为 0 才真正补货。
        try:
            await asyncio.sleep(0.5)
            count2 = await self._check_inventory_level(block_id)
            if count2 > 0:
                self._activity("debug",
                               f"背包二次确认 {clean_id} ×{count2}（首次读到 0 为 Via 数据滞后）→ 重试装备")
                if await self._try_select_item(clean_id, block_id):
                    return True
                return False
        except Exception:
            pass  # 二次确认失败按"确实无货"处理（继续补货）

        # 背包中没有该物品 → 补货（2026-08-14：全量补齐所有缺的材料再返回，
        # 避免"缺A补A、回来又缺B再传送"的反复奔波）
        logger.info("[%s] %s 用完了，开始补货...", self.bot_id, clean_id)
        self._activity("warn", f"缺少 {clean_id}，开始补货")
        if await self._do_full_restock(clean_id):
            # 补货后刷新 hotbar_map 并重试
            await self._refresh_hotbar_map()
            if await self._try_select_item(clean_id, block_id):
                return True
        logger.warning("[%s] 补货后仍无法装备 %s，跳过该材料", self.bot_id, clean_id)
        return False

    async def _try_select_item(self, clean_id: str, block_id: str) -> bool:
        """Select/equip item; returns True only if the hand now holds it."""
        try:
            result = await self.mcp.select_hotbar_item(clean_id)
            if result.get("success"):
                # ⚠️ 2026-08-16：Via 下 select 可能"假成功"（服务器切换后客户端
                # heldItem 未同步/equip 未生效）——成功后用 get_player_state.held_item
                # 验证实际手持，不符则视为失败（防手持错误物品放置 → WRONG abort）。
                try:
                    _st = await self.mcp.get_player_state()
                    _d2 = _st.get("data", _st) if isinstance(_st, dict) else {}
                    _held = _d2.get("held_item") or ""
                    if not _held or self._normalize_item_id(_held) != self._normalize_item_id(clean_id):
                        logger.warning("[%s] select %s 后手持 %s（切换未生效）→ 视为失败",
                                       self.bot_id, clean_id, _held or "空")
                        return False
                except Exception:
                    pass  # 读取失败不拦截（保持原行为）
                self._current_item = block_id
                # 2026-08-14 模块B：记录实际槽位到 hotbar_map（存归一化 ID）
                slot = result.get("slot")
                if isinstance(slot, int) and 0 <= slot <= 8:
                    self._hotbar_map[slot] = self._normalize_item_id(clean_id)
                    self._current_slot = slot
                return True
            logger.warning("[%s] select_hotbar_item %s failed: %s",
                           self.bot_id, clean_id, result.get("error", "?"))
        except Exception as e:
            logger.warning("[%s] select_hotbar_item %s error: %s",
                           self.bot_id, clean_id, e)
        return False

    async def _refresh_hotbar_map(self) -> None:
        """从 get_inventory_snapshot 重建快捷栏映射（补货后/物品移动后）。

        2026-08-14 修复：snapshot type 无前缀，统一 _normalize_item_id 存储，
        否则 _ensure_item_in_hand 用带前缀 clean_id 查缓存永远不命中（缓存失效）。
        """
        try:
            snap = await self.mcp.get_inventory_snapshot(inventory_id=0)
            items = (snap.get("data", snap)).get("items", [])
            self._hotbar_map.clear()
            for s in items:
                slot = s.get("slot")
                if isinstance(slot, int) and 0 <= slot <= 8:
                    item_id = self._normalize_item_id(s.get("type", ""))
                    if item_id:
                        self._hotbar_map[slot] = item_id
        except Exception:
            pass  # 静默失败，不影响建造

    async def _get_player_pos(self) -> Optional[tuple[float, float]]:
        """获取 bot 当前 X/Z 坐标（实时优先，缓存兜底）。

        2026-08-15 第二批修复（D1/D14）：last_status 是 status 事件每 5s 推送的缓存，
        传送后/刚启动时可能是旧位置——现改为「实时 get_player_state 优先」，
        last_status 仅作为实时查询失败时的兜底（避免用过期数据误判"不在建造区域"）。
        """
        p = await self._get_player_pos_full()
        return (p[0], p[1]) if p else None

    async def _get_player_pos_full(self) -> Optional[tuple[float, float, float]]:
        """获取 bot 当前位置 (x, z, y)（实时优先，缓存兜底）；获取不到返回 None。

        y 供 _near_build_area 高度校验（D2）；实时 get_player_state 返回 location 字段。
        """
        def _extract3(st: dict) -> Optional[tuple[float, float, float]]:
            if not isinstance(st, dict):
                return None
            pos = (st.get("position") or st.get("pos")
                   or st.get("location")  # 2026-08-15：get_player_state 返回的是 location 字段
                   or st.get("player") or st.get("entity") or {})
            if isinstance(pos, dict):
                x, y, z = pos.get("x"), pos.get("y"), pos.get("z")
                if all(isinstance(v, (int, float)) for v in (x, y, z)):
                    return (float(x), float(z), float(y))
            elif isinstance(pos, (list, tuple)) and len(pos) >= 3:
                if all(isinstance(v, (int, float)) for v in pos[:3]):
                    return (float(pos[0]), float(pos[2]), float(pos[1]))
            return None
        # 1) 实时查询优先（~几百 ms，避免用过期的 5s 推送缓存）
        try:
            r = await self.mcp.get_player_state()
            data = r.get("data", r) if isinstance(r, dict) else {}
            if isinstance(data, dict):
                p = _extract3(data)
                if p:
                    return p
                # 部分实现 position 在 data 的 status 子对象里
                p = _extract3(data.get("status") or data.get("bot_status") or {})
                if p:
                    return p
        except Exception:
            pass
        # 2) 缓存兜底（实时查询失败时用 last_status，可能略旧但总比没有强）
        try:
            p = _extract3(getattr(self.mcp, "last_status", None) or {})
            if p:
                return p
        except Exception:
            pass
        return None

    def _near_whitelist(self, x: float, z: float, radius: float = 6.0) -> bool:
        """是否在补货点白名单区域（2026-08-18 猪排仓库 food_boxes；2026-08-19 强化）。

        区域判定 = 「维度 + 坐标 + 半径」：
          · 坐标：与白名单坐标（x,z）曼哈顿距离 ≤ radius
          · 维度：bot 当前维度必须在补货点维度白名单内（默认末地）
        bot 在仓库取猪排时高度与建造层差异巨大，若 y 校验误判会触发兜底传送
        把 bot 从仓库拉走。白名单内坐标【且同维度】跳过 y 校验。
        """
        if not self._y_whitelist:
            return False
        try:
            # 维度检查：bot 必须在补货点维度（防坠落主世界地表被误放行）
            st = getattr(self.mcp, "last_status", None) or {}
            if isinstance(st, dict) and st.get("dimension") and self._whitelist_dims:
                cur_dim = str(st.get("dimension"))
                if cur_dim not in self._whitelist_dims:
                    return False
            for wx, wz in self._y_whitelist:
                if abs(float(x) - wx) <= radius and abs(float(z) - wz) <= radius:
                    return True
        except Exception:
            pass
        return False

    def _near_build_area(self, x: float, z: float, y: Optional[float] = None) -> bool:
        """判断 (x,z)（可选 y）是否在建造区域附近（矩形区域，X/Z 半宽半高各自外扩自适应余量）。

        2026-08-14 优化（为大地图画准备）：
        - 区域边界首次调用时计算并缓存（O(N) 一次 → 之后 O(1)）——原实现每次
          全量遍历 block_matrix，128²=1.6万 尚可，512²/1024²=26万~100万+ 会卡。
        - 矩形判断（X、Z 分别算半宽半高）——原实现只用 X 方向半径（圆形），
          对纵向长条/宽幅地图画会误判（区域远端被判"不在区域内"触发误兜底）。
        - 余量自适应：min(宽, 高) 的 10%，下限 40 格——小图（128）≈40 格、
          大图（512+）自动放大，覆盖传送落点偏差又不至于过度外扩。
        2026-08-15 第二批（D2）：可选 y 高度校验——bot 站立层 = origin_y-1（地面），
        偏离 >3 格视为不在建造区域（防止 x/z 正确但高度错误的传送落点误判）。
        """
        bounds = self._area_bounds
        if bounds is None:
            try:
                xs = [k[0] for k in self.block_matrix]
                zs = [k[1] for k in self.block_matrix]
                if not xs or not zs:
                    self._area_bounds = (0.0, 0.0, 0.0, 0.0)  # 未知区域：不拦截
                    return True
                w = float(max(xs) - min(xs))
                h = float(max(zs) - min(zs))
                margin = max(40.0, min(w, h) * 0.10)
                cx = self.origin_x + (min(xs) + max(xs)) / 2.0
                cz = self.origin_z + (min(zs) + max(zs)) / 2.0
                bounds = (cx, cz, w / 2.0 + margin, h / 2.0 + margin)
                self._area_bounds = bounds
            except Exception:
                return True
        cx, cz, half_w, half_h = bounds
        if half_w <= 0 or half_h <= 0:
            return True  # 未知区域不拦截（避免误判导致无限兜底）
        if y is not None:
            # ⚠️ 2026-08-18 用户需求：猪排仓库（food_boxes）加入 y 轴白名单——
            # bot 在仓库取猪排时 y=58（末地）与建造层差异巨大，跳过 y 校验，
            # 避免误判"不在建造区域/未到位"触发兜底传送把 bot 从仓库拉走。
            if not self._near_whitelist(x, z):
                expected_y = self.origin_y + self._stand_y_offset  # 站立层（地面）
                if abs(y - expected_y) > 3.0:
                    return False
        return abs(x - cx) <= half_w and abs(z - cz) <= half_h

    async def _send_teleport(self, cmd: str) -> bool:
        """发送传送指令并等待落地；失败返回 False。"""
        try:
            r = await self.mcp.send_chat(cmd)
            if isinstance(r, dict) and r.get("success") is False:
                self._activity("warn", f"传送失败：{r.get('error', '?')}")
                return False
            # 2026-08-15 修复：等 3.5s 落地稳定（原 2.5s 在悬空传送点/平台边缘时
            # bot 未落地，验证瞬间通过但下一秒掉下平台）
            await asyncio.sleep(3.5)
            self._last_pos = None  # 传送后位置未知，强制重新寻路
            return True
        except Exception as e:
            self._activity("warn", f"传送异常：{e}")
            return False

    async def _get_bot_environment(self) -> dict:
        """读取 bot 当前维度/位置/所在领地/附近领地（结合后端 bluemap residences）。

        返回 {dimension, location, current_residence, nearby_residences}；
        任一项获取失败时为 None/[]，不影响主流程（只用于诊断与校验）。
        """
        env: dict = {
            "dimension": None,
            "location": None,
            "current_residence": None,
            "nearby_residences": [],
        }
        try:
            st = await self.mcp.get_player_state()
            d = st.get("data", st) if isinstance(st, dict) else {}
            loc = d.get("location") or {}
            env["location"] = loc or None
            env["dimension"] = d.get("dimension") or None
        except Exception:
            pass
        loc = env.get("location") or {}
        x, z, y = loc.get("x"), loc.get("z"), loc.get("y", 64)
        if x is None or z is None:
            return env
        try:
            from vmtools_next.main import get_bluemap_monitor
            mon = get_bluemap_monitor()
            if mon is None:
                return env
            rs = mon.get_residences() or []
            # mineflayer dimension 值 → bluemap 世界名（Residence marker 的 world 字段）
            bm_world = {
                "overworld": "world",
                "world_nether": "world_nether",
                "world_the_end": "world_the_end",
            }.get(env.get("dimension") or "", env.get("dimension") or "")
            dists: list = []
            for r in rs:
                w = r.get("world") or ""
                if w and w != bm_world:
                    continue
                shape = r.get("shape") or []
                if len(shape) >= 3:
                    my = r.get("min_y", -1e9) or -1e9
                    My = r.get("max_y", 1e9) or 1e9
                    if my <= y <= My and _point_in_polygon_2d(x, z, shape):
                        env["current_residence"] = {
                            "name": r.get("label"),
                            "owner": r.get("owner"),
                            "area": r.get("area"),
                        }
                p = r.get("position") or {}
                px, pz = p.get("x"), p.get("z")
                if px is not None and pz is not None:
                    d2 = (px - x) ** 2 + (pz - z) ** 2
                    dists.append((d2, r.get("label"), r.get("owner")))
            env["nearby_residences"] = [
                {"name": n, "owner": o, "distance": round(d2 ** 0.5, 1)}
                for d2, n, o in sorted(dists)[:5]
            ]
        except Exception:
            pass
        return env

    async def _check_build_environment(self) -> dict:
        """启动建造前检查：维度 + 可自定义领地（config.map_art_residence / map_art_build_world）。

        只做诊断与告警（不符合预期不终止，由后续传送定位/兜底链继续处理）：
        - bot 在错误维度（如补货后被留在末地仓库）→ 警告，提醒会尝试传送回建造点
        - bot 所在领地 ≠ 配置的建造领地 → 警告（领地可自定义，空=不校验）
        同时输出「附近领地」列表帮助确认 bot 当前位置。
        """
        env = await self._get_bot_environment()
        loc = env.get("location") or {}
        res = env.get("current_residence") or {}
        res_name = res.get("name") or "无/未知"
        nearby = env.get("nearby_residences") or []
        nearby_names = "、".join(str(n.get("name")) for n in nearby[:5]) or "无"
        self._activity(
            "info",
            f"环境检测：维度={env.get('dimension')} 位置=({loc.get('x', '?')},{loc.get('z', '?')}) "
            f"所在领地={res_name} 附近领地={nearby_names}")
        dim = env.get("dimension")
        if dim and self._build_world and dim != self._build_world:
            self._activity(
                "warn",
                f"⚠️ bot 维度 {dim} ≠ 建造维度 {self._build_world}——bot 可能在错误世界"
                f"（如补货后被留在末地仓库），将尝试传送回建造点")
        if self._build_residence and res_name not in ("无/未知", None):
            if str(res_name).lower() != self._build_residence.lower():
                self._activity(
                    "warn",
                    f"⚠️ bot 所在领地 {res_name} ≠ 配置的建造领地 {self._build_residence}"
                    f"——若 bot 能传送回建造点则继续，否则检查领地权限/坐标")
        return env

    async def _verify_at_build_area(self, retries: int = 2) -> Optional[str]:
        """传送后验证 bot 是否真的回到建造区域附近（2026-08-16 P0-4 改造）。

        返回 None = 验证通过；否则返回失败原因标签（供 _try_teleport_home 分流）：
          - "teleport_no_effect"  ：多次无法获取位置 / 位置不在建造区域（传送未生效或传错位置）
          - "fall_after_teleport" ：位置对但高度不符 / 未落地 / 复查漂移（传回后再次坠落/悬空）

        2026-08-16 修复（用户实测乱走）：传送后 bot 可能还在下落（传送到平台顶前有
        落差），立即读位置 y 偏低（如 62.8 vs 站立层 69）→ 误判"高度不符"→ fall_after_teleport
        → 反复传送死循环。开头先等落地稳定（on_ground + 位置稳定）再验证。
        """
        # 先等落地稳定（上限 5s）：传送到平台顶很快通过；传送到高空等落地；水上浮着
        # on_ground=true 但高度仍不符 → 由下方高度校验判失败（正确）。
        try:
            await self._wait_landed(timeout_s=5.0)
        except Exception:
            pass
        for attempt in range(retries + 1):
            if attempt > 0:
                await asyncio.sleep(1.5)
            p = await self._get_player_pos_full()
            if p is None:
                if attempt < retries:
                    self._activity("debug",
                                   f"传送后位置获取失败，{1.5}s 后重试（{attempt + 1}/{retries}）")
                    continue
                self._activity("warn", "传送后多次尝试仍无法获取 bot 位置——判定传送未生效")
                return "teleport_no_effect"
            x, z, y = p
            expected_y = self.origin_y + self._stand_y_offset  # 站立层（平台顶）
            # ⚠️ 2026-08-16 修复：bot 坐标 y = 脚的位置。站在地图画方块（y=69）上
            # 脚 y=70（偏差1.0）是正常位置（边放边踩后站在已放方块上），
            # 原 `>=1.0` 把 1.0 判为不符 → 传送后反复误判"高度不符"兜底循环。
            # 统一用 _verify_y_tol（>容差才失败），与 _move_to verify_height 一致。
            if abs(float(y) - expected_y) > self._verify_y_tol:
                # ⚠️ 2026-08-18 用户需求：猪排仓库（food_boxes）加入 y 轴白名单——
                # bot 在仓库取猪排时 y=58（末地）与建造层差异巨大，若误判高度不符会
                # 触发 fall_after_teleport（等待落地→复验→再失败）死循环。
                if not self._near_whitelist(x, z):
                    self._activity("warn",
                                   f"传送后高度不符（站立层={expected_y}，实际y={y:.1f}）——"
                                   f"判定未到位（可能悬空/掉水），走兜底")
                    return "fall_after_teleport"
            if self._near_build_area(x, z):  # x/z 判断（y 已单独严格校验）
                # 复查：等 1.5s 再确认位置没变（防悬空瞬间验证通过后掉下去）
                await asyncio.sleep(1.5)
                try:
                    st = await self.mcp.get_player_state()
                    d2 = st.get("data", st) if isinstance(st, dict) else {}
                    on_ground = d2.get("is_on_ground")
                    if on_ground is False:
                        self._activity("warn",
                                       f"传送后 bot 未落地（on_ground=False，悬空/水中）——判定未到位，走兜底")
                        return "fall_after_teleport"
                except Exception:
                    pass
                p2 = await self._get_player_pos_full()
                if p2 is None:
                    self._activity("debug",
                                   f"传送后位置验证通过（{x:.0f},{z:.0f},y={y:.0f}），复查位置获取失败视为通过")
                    return None
                x2, z2, y2 = p2
                if (abs(x2 - x) > 3.0 or abs(z2 - z) > 3.0
                        or abs(float(y2) - expected_y) > self._verify_y_tol):
                    self._activity("warn",
                                   f"传送后位置复查异常（初始{x:.0f},{z:.0f},y={y:.0f}→复查"
                                   f"{x2:.0f},{z2:.0f},y={y2:.0f}）——bot 未稳定，判定未到位")
                    return "fall_after_teleport"
                self._activity("debug",
                               f"传送后位置验证通过（{x:.0f},{z:.0f},y={y:.0f}）在建造区域附近")
                return None
            self._activity("warn",
                           f"传送后位置不在建造区域（{x:.0f},{z:.0f},y={y:.0f}），需固定指令兜底")
            return "teleport_no_effect"
        return "teleport_no_effect"

    async def _wait_landed(self, timeout_s: float = 5.0) -> bool:
        """落地稳定化（P0-4）：等待 bot 真正落地（is_on_ground=true 且位置稳定）。

        用于「传回后再次坠落」场景——bot 传送到悬空处/水中时，先等落地稳定
        再验证，避免反复「传送→坠落→再传送」的空转。
        """
        try:
            t0 = time.monotonic()
            last_y = None
            stable_ticks = 0
            while time.monotonic() - t0 < timeout_s:
                st = await self.mcp.get_player_state()
                d2 = st.get("data", st) if isinstance(st, dict) else {}
                on_ground = d2.get("is_on_ground")
                loc = d2.get("location") or {}
                cy = loc.get("y")
                if on_ground is True and isinstance(cy, (int, float)):
                    if last_y is not None and abs(float(cy) - last_y) < 0.05:
                        stable_ticks += 1
                        if stable_ticks >= 3:  # 连续 3 次采样位置稳定且落地
                            return True
                    else:
                        stable_ticks = 0
                    last_y = float(cy)
                await asyncio.sleep(0.6)
            return False
        except Exception:
            return False

    async def _try_teleport_home(self, reason: str = "") -> bool:
        """传送回建造点（2026-08-16 P0-4 兜底状态机，替换原固定三级链）：

        分级与失败原因分流：
          1) 临时点传送（/ehomes dth）——每级内重试 _tp_retry_each 次；
             · teleport_no_effect（传送未生效/传错位置）→ 换下一级传送；
             · fall_after_teleport（传回后坠落/未落地）→ 先 _wait_landed 落地稳定化，
               稳定后再验证，仍失败才换级；
          2) 固定指令兜底（return_fixed，如 /ehomes mapart）——同策略；
          3) pathfinder + 蹲搭走回建造区（传送链全失败时的自愈）。
        总尝试上限 _tp_retry_total（默认 8）——防「传送未生效」死循环空转；
        每次失败记录原因标签/次数/耗时（P2-1 兜底决策日志）。
        """
        t_start = time.monotonic()
        attempts = 0
        fail_log: list[str] = []

        async def _try_tp(cmd: str) -> bool:
            nonlocal attempts
            for _i in range(self._tp_retry_each):
                if self._stopped:
                    return False
                attempts += 1
                if attempts > self._tp_retry_total:
                    self._activity("error",
                                   f"传送兜底尝试次数超上限（{self._tp_retry_total}），放弃")
                    return True  # 占位：实际返回 True 会导致误判成功——由调用方校验位置
                if not await self._send_teleport(cmd):
                    fail_log.append(f"{cmd}:send_fail")
                    continue
                verify = await self._verify_at_build_area()
                if verify is None:
                    return True
                fail_log.append(f"{cmd}:{verify}")
                if verify == "fall_after_teleport":
                    # 传回后坠落 → 先落地稳定化再复验（区分于传送未生效）
                    self._activity("warn", "传送到位但未稳定（坠落/悬空），等待落地稳定后复验…")
                    if await self._wait_landed():
                        verify2 = await self._verify_at_build_area()
                        if verify2 is None:
                            return True
                        fail_log.append(f"{cmd}:landed:{verify2}")
            return False

        # 1) 临时点传送（分级重试）
        cmd = self._supply_cfg.get("return", "/ehomes dth")
        if reason:
            self._activity("warn", f"{reason}，传送回建造点（{cmd}）")
        else:
            self._activity("info", f"传送回建造点（{cmd}）")
        if await _try_tp(cmd):
            self._activity("debug", f"传送兜底成功（{cmd}，共尝试 {attempts} 次，耗时 {time.monotonic() - t_start:.1f}s）")
            return True

        # 1.5) 2026-08-18 用户反馈（新任务"不在建造区域"死循环）：dth 是上次保存的
        # 临时点——可能是【旧任务】的坐标（睡觉/补货往返保存的 dth 来自旧建造点），
        # 传过去永远不在新任务区域。直接用本任务 origin /tp 传送到建造区，
        # 不依赖任何历史临时点/固定点。
        if self.origin_x is not None:
            tp_origin = f"/tp {self.origin_x} {self.origin_y + self._stand_y_offset} {self.origin_z}"
            self._activity("warn", f"临时传送点不在本任务区域，改用任务 origin 传送（{tp_origin}）")
            if await _try_tp(tp_origin):
                self._activity("debug",
                               f"任务 origin 传送成功（{tp_origin}，共尝试 {attempts} 次，耗时 {time.monotonic() - t_start:.1f}s）")
                return True

        # 2) 固定指令兜底（2026-08-15：DB 未配置 return_fixed 时回退默认 /ehomes mapart）
        fixed = (self._supply_cfg.get("return_fixed") or "/ehomes mapart").strip()
        if fixed and fixed != cmd:
            self._activity("warn", f"临时传送点不可用，改用固定指令兜底（{fixed}）")
            if await _try_tp(fixed):
                self._activity("debug", f"传送兜底成功（{fixed}，共尝试 {attempts} 次，耗时 {time.monotonic() - t_start:.1f}s）")
                return True

        # 3) 2026-08-15 新增：pathfinder + 蹲搭走回建造区（传送链全失败时的自愈）
        self._activity("warn", f"传送回建造点失败（{attempts} 次，原因 {';'.join(fail_log) or 'unknown'}），尝试寻路走回")
        try:
            gx, gy, gz = self.resume_anchor()
            ok = await self._move_to(gx, gy, gz, max_offset=3,
                                     label="walk back to build area",
                                     timeout_ms=30000,
                                     allow_scaffold=True,  # 允许蹲搭搭路（悬崖/落差）
                                     verify_height=True)
            if ok:
                self._activity("info", f"寻路走回建造区成功（{gx},{gy},{gz}）")
                return True
        except Exception as e:
            logger.warning("[%s] Walk-back to build area failed: %s", self.bot_id, e)
        self._activity("warn",
                       f"传送与寻路走回均失败，无法返回建造点（总尝试 {attempts} 次，耗时 {time.monotonic() - t_start:.1f}s）")
        return False

    @staticmethod
    def _normalize_item_id(item_id: str) -> str:
        """统一物品 ID：去 minecraft: 前缀 + 去 [后缀（1.21 组件数据）。

        2026-08-14 修复：get_inventory_snapshot 返回的 type 是 "white_concrete"
        （不带前缀），而 DB/配置/block_matrix 里是 "minecraft:white_concrete"
        （带前缀）→ 直接 == 比较永远失败 → 背包明明有货却判定"无/缺"（用户实测
        "取到方块却显示补货失败""背包有方块却显示无方块"的根因）。
        """
        if not item_id:
            return ""
        item_id = str(item_id).split("[")[0].strip()
        if item_id.startswith("minecraft:"):
            item_id = item_id[len("minecraft:"):]
        return item_id

    def _supply_boxes_for(self, item_id: str) -> list:
        """按归一化 ID 查找该材料的潜影盒坐标（supply_boxes key 兼容带/不带前缀）。"""
        norm = self._normalize_item_id(item_id)
        for key, boxes in self._supply_boxes.items():
            if self._normalize_item_id(key) == norm:
                return boxes
        return []

    def _pick_restock_material(self) -> Optional[str]:
        """选一种要补货的材料：优先已配置潜影盒的、其次当前区域需要的方块。"""
        # 1) 已配置补货潜影盒的材料（用户明确指定了坐标，最可靠）
        if self._supply_boxes:
            return next(iter(self._supply_boxes))
        # 2) 从 block_matrix 选第一个非空气方块
        for (_x, _z), bid in self.block_matrix.items():
            clean = bid.split("[")[0] if "[" in bid else bid
            if clean and self._normalize_item_id(clean) != "air":
                return clean
        return None

    async def _ensure_scaffold_material(self) -> bool:
        """蹲搭前确保背包有可放置方块（任务材料或常见方块）；没有则先补货。

        2026-08-14：蹲搭需要用手头的方块，背包只有食物/工具时搭不了——先补货
        （从配置的潜影盒拿任务材料）再蹲搭。
        """
        # 任务需要的材料集合（这些必然是方块；2026-08-14 统一归一化去前缀）
        task_materials: set[str] = set()
        for (_x, _z), bid in self.block_matrix.items():
            clean = self._normalize_item_id(bid)
            if clean and clean != "air":
                task_materials.add(clean)
        # 常见可放置方块（即使不是任务材料也能搭路；归一化无前缀）
        common = {
            "dirt", "cobblestone", "stone",
            "gravel", "sand", "grass_block",
            "cobbled_deepslate", "oak_planks",
        }
        try:
            snap = await self.mcp.get_inventory_snapshot(inventory_id=0)
            items = (snap.get("data", snap)).get("items", [])
            have: list[str] = []
            for s in items:
                item_id = self._normalize_item_id(s.get("type", ""))
                cnt = s.get("count", 0)
                if cnt > 0 and item_id:
                    have.append(f"{item_id}×{cnt}")
                    if item_id in task_materials or item_id in common:
                        self._activity("debug", f"背包有可放置方块 {item_id}×{cnt}，可直接蹲搭")
                        return True  # 背包有可放置方块，可直接蹲搭
            self._activity("debug", f"背包物品：{('，'.join(have[:20])) if have else '（空）'}——无可用方块，需补货")
        except Exception as e:
            self._activity("debug", f"背包检查失败：{e}（按无可放置方块处理，去补货）")

        # 背包无可放置方块 → 补货一种任务材料（2026-08-14：全量补齐，蹲搭材料也有了）
        material = self._pick_restock_material()
        if not material:
            self._activity("warn", "背包无方块且无可补货材料，无法蹲搭")
            return False
        self._activity("warn", f"背包无方块，先补货 {material} 再蹲搭")
        if await self._do_full_restock(material):
            await self._refresh_hotbar_map()
            return True
        self._activity("warn", f"补货 {material} 失败，无法蹲搭")
        return False

    async def _check_inventory_level(self, block_id: str) -> int:
        """Scan player inventory and return count of block_id.

        2026-08-14 修复：snapshot type 无 minecraft: 前缀，DB 配置带前缀——
        统一 _normalize_item_id 后比较（原 == 永远失败 → 明明有货判定缺货）。
        """
        norm = self._normalize_item_id(block_id)
        try:
            snap = await self.mcp.get_inventory_snapshot(inventory_id=0)
            items = (snap.get("data", snap)).get("items", [])
            total = sum(
                s.get("count", 0)
                for s in items
                if self._normalize_item_id(s.get("type", "")) == norm
            )
            return total
        except Exception:
            return 0

    @staticmethod
    def _default_supply_cfg() -> dict:
        """任务未配置时使用全局默认三个传送指令（config.py map_art_supply_*_command）。

        2026-08-14：新增 return_fixed——固定返回指令（死亡/意外导致临时点 dth
        不在地图画区域时的兜底传送，如 /ehomes mapart 或 /tp x y z）。
        """
        try:
            mf = get_config().mineflayer
            return {
                "go": getattr(mf, "map_art_supply_go_command", "/ehomes mdssj") or "/ehomes mdssj",
                "save": getattr(mf, "map_art_supply_save_command", "/esethomes dth") or "/esethomes dth",
                "return": getattr(mf, "map_art_supply_return_command", "/ehomes dth") or "/ehomes dth",
                "return_fixed": getattr(mf, "map_art_supply_fixed_return_command", "/ehomes mapart") or "/ehomes mapart",
            }
        except Exception:
            return {"go": "/ehomes mdssj", "save": "/esethomes dth", "return": "/ehomes dth",
                    "return_fixed": "/ehomes mapart"}

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

    @_restock_serialized
    async def _do_full_restock(self, trigger_item: str) -> bool:
        """全量补货（2026-08-15 第一批重构：target/have 模型 + 模块化执行）。

        迁移 playercontrolpp AutoRestockFeature 的决策模型：
        - 缺料判定：区域材料需求（RestockPlanner.region_material_count）中
          背包散装量 < target（target = min(区域剩余需求, map_art_restock_stacks×64)，
          默认 4 组 = 256）的材料，按满足度（have/target）最低优先排序取料
        - 未配置潜影盒坐标的材料：提示并跳过（用户确认，不再静默失败）
        - 执行：ShulkerRestocker（dryTicks 取空记忆 + 背包满检查 + withdraw 背包确认），
          传送只做一次（暂存→仓库→逐个取→返回），补两轮 + 全量复查
        - 零收获总闸：连续 3 轮补货无收获 → 终止本 bot 区域（防缺料死循环）
        """
        clean_trigger = self._normalize_item_id(trigger_item)
        # B1 修复：最小补货间隔（历史只写不读 → 缺料时高频往返传送）
        _now = time.monotonic()
        if self._last_restock_at > 0 and (_now - self._last_restock_at) < self._min_restock_interval_s:
            self._activity(
                "debug",
                f"距上次补货 {_now - self._last_restock_at:.0f}s < "
                f"{self._min_restock_interval_s:.0f}s，跳过本次补货")
            return False
        self._last_restock_at = _now

        # 1) 区域材料需求 + 背包现状（target/have 模型；区域需求缓存一次）
        if self._region_materials is None:
            _b = self.work_bounds()
            self._region_materials = RestockPlanner.region_material_count(
                self.block_matrix, Region(_b[0], _b[1], _b[2], _b[3]),
                self.origin_x, self.origin_z)
        have_counts: dict[str, int] = {}
        for mat in self._region_materials:
            have_counts[mat] = await self._check_inventory_level(mat)
        planner = RestockPlanner(stacks_per_item=self._restock_stacks)
        needs = planner.compute_needs(self._region_materials, have_counts, self._supply_boxes)

        # 2) 触发材料强制加入（区域统计可能未覆盖/已满足但本次就是要用它）
        # ⚠️ 2026-08-18 修复（用户反馈：材料不缺仍补货→超64）：原条件 have_trigger<64
        # 会把「背包还有几十个（如 50）」的材料也强制补到 256 → 超量。改为仅当
        # 背包【完全没有】该材料（have_trigger<1）才强制加入补货——已有部分材料时
        # 靠 _try_select_item 重试即可，不应触发补货。target 固定 64（一组，不再 4 组）。
        if not any(n.item_id == clean_trigger for n in needs):
            have_trigger = await self._check_inventory_level(clean_trigger)
            if have_trigger < 1:  # 2026-08-18：仅完全无货才补
                needs.append(Need(
                    item_id=clean_trigger,
                    target=64,  # 2026-08-18：只补一组（用户：每种只拿一组）
                    have=have_trigger,
                    boxes=self._supply_boxes_for(clean_trigger),
                ))
                needs.sort(key=lambda n: (n.ratio, n.item_id))
        if not needs:
            self._activity("info", "背包材料充足，无需补货")
            return True

        # 未配置坐标的材料：提示并跳过（用户确认）
        unboxed = [n.item_id for n in needs if not n.boxes]
        if unboxed:
            self._activity("warn",
                           f"以下材料任务需要但未配置潜影盒坐标，将跳过：{'，'.join(unboxed)}")
        need_with_boxes = [n for n in needs if n.boxes]
        if not need_with_boxes:
            self._activity("warn", "所有缺料均未配置潜影盒坐标，无法补货")
            return False
        self._activity("warn",
                       f"需补货材料（{len(need_with_boxes)}种，按缺货程度排序）："
                       f"{'，'.join(f'{n.item_id}({n.have}/{n.target})' for n in need_with_boxes)}")

        # 3) 暂存当前位置 → 传送仓库 → 等 chunk 加载
        self.progress.state = "restocking"
        try:
            r1 = await self.mcp.send_chat(self._supply_cfg.get("save", "/esethomes dth"))
            if isinstance(r1, dict) and r1.get("success") is False:
                logger.warning("[%s] save command failed: %s", self.bot_id, r1.get("error", "?"))
                return False
            self._activity("info", f"暂存当前位置（{self._supply_cfg.get('save', '/esethomes dth')}）")
            await asyncio.sleep(1.5)
            r2 = await self.mcp.send_chat(self._supply_cfg.get("go", "/ehomes mdssj"))
            if isinstance(r2, dict) and r2.get("success") is False:
                logger.warning("[%s] go command failed: %s", self.bot_id, r2.get("error", "?"))
                return False
            self._activity("info", f"传送前往仓库（{self._supply_cfg.get('go', '/ehomes mdssj')}）")
            self._activity("debug", "传送指令已发出，等待 3.5s 让 chunk 加载、bot 落地...")
            await asyncio.sleep(3.5)
            self._activity("debug", "等待完成，开始逐个取货")

            # 4) ShulkerRestocker 逐个补齐（满足度最低优先；dryTicks/背包满/背包确认；补两轮）
            restocker = self._get_restocker()
            restocker.reset_drained()
            for _round in range(2):
                if not need_with_boxes:
                    break
                next_round: list = []
                for need in need_with_boxes:
                    have = await restocker.restock_material(need.item_id, need.target, need.boxes)
                    if have < need.target:
                        next_round.append(need)
                need_with_boxes = next_round
                if need_with_boxes:
                    self._activity("warn",
                                   f"第一轮补货后仍缺：{'，'.join(n.item_id for n in need_with_boxes)}，再补一轮")
            still_missing = [n.item_id for n in need_with_boxes]

            # 5) 返回建造点（报告最终缺失 + 零收获总闸）
            if still_missing:
                self._activity("warn",
                               f"补货结束仍有缺失（{len(still_missing)}种）：{'，'.join(still_missing)}——"
                               f"可能是潜影盒取空/坐标不符，回建造点后再试")
                # 本次有收获（至少一种补到 target）→ 重置计数；全无收获 → 累计
                gained = False
                for n in needs:
                    if n.boxes and await self._check_inventory_level(n.item_id) >= n.target:
                        gained = True
                        break
                if not gained:
                    self._no_gain_cycles += 1
                    if self._no_gain_cycles >= 3:
                        self._activity("error",
                                       "连续 3 轮补货零收获，判定材料严重不足，终止本 bot 区域")
                        self._stopped = True  # 主循环将退出（防缺料死循环）
                else:
                    self._no_gain_cycles = 0
            else:
                self._no_gain_cycles = 0
                self._activity("info", f"全部补齐（{len(needs)}种材料均已确认在背包）")
            self._activity("info", f"传送返回建造点（{self._supply_cfg.get('return', '/ehomes dth')}）")
            try:
                r_ret = await self.mcp.send_chat(self._supply_cfg.get("return", "/ehomes dth"))
                # 2026-08-15 修复：检查返回指令是否真正发出（原 try/except 吞掉 success:false，
                # 曾导致 save 指令错误（/esethome 单数）时 dth 家未保存、返回传送静默失败）
                if isinstance(r_ret, dict) and r_ret.get("success") is False:
                    self._activity("warn",
                                   f"返回指令发送失败：{r_ret.get('error', '?')}（检查 supply_config 的 save/return 指令）")
                await asyncio.sleep(1.5)
            except Exception as e:
                self._activity("warn", f"返回指令异常：{e}")
                await asyncio.sleep(1.5)
            self._last_pos = None  # 传送后位置未知，强制下次寻路
            self.progress.state = "placing"
            # ⚠️ 2026-08-16 修复：Via 传送后客户端背包数据延迟且可能【部分】同步
            # （不同槽位数据到达时间不一）——原"等背包非空就 break"可能只等到部分
            # 材料（如 gray/white 在、black 未到）→ check(black)=0 → 误判补货失败。
            # 改为【轮询等待目标材料（clean_trigger）出现】（最多 10s），确保 select 前
            # 该材料数据已就绪。
            for _wait in range(20):
                try:
                    if (await self._check_inventory_level(clean_trigger)) > 0:
                        break
                except Exception:
                    pass
                await asyncio.sleep(0.5)
            await self._refresh_hotbar_map()
            # ⚠️ 2026-08-16 修复：返回「目标材料（clean_trigger）是否已取到」，而非
            # not still_missing——个别材料缺失（如 cyan 盒子放错成 orange，供应链
            # 问题）会导致整体返回 False → 调用方 `_ensure_item_in_hand` 误判
            # 目标材料补货失败 → 连 select 都不执行 → "补货后仍无法装备" → 缺块。
            try:
                _have_target = (await self._check_inventory_level(clean_trigger)) > 0
            except Exception:
                _have_target = not still_missing
            return _have_target
        except Exception as e:
            logger.warning("[%s] Full restock failed: %s", self.bot_id, e)
            self._activity("warn", f"全量补货异常：{e}")
            return False

    async def _verify_warehouse_arrived(self, boxes: list, timeout_s: float = 10.0) -> bool:
        """传送后验证 bot 是否真的到了仓库（2026-08-16 用户反馈修复）。

        仓库在末地（mdssj/zhurou 传送点），若传送失败/未生效 bot 还在主世界，却去
        寻路/开箱末地盒子坐标 → "No container near" → 补货失败（状态显示 restocking
        但实际在主世界，状态与位置矛盾）。以「与任一目标盒子水平距离 < 100 格」判断
        是否到位（不同维度的坐标水平距离必远超 100，天然区分维度）。
        """
        try:
            t0 = time.monotonic()
            while time.monotonic() - t0 < timeout_s:
                st = await self.mcp.get_player_state()
                d2 = st.get("data", st) if isinstance(st, dict) else {}
                loc = d2.get("location") or {}
                px, pz = loc.get("x"), loc.get("z")
                if isinstance(px, (int, float)) and isinstance(pz, (int, float)):
                    for bx, _by, bz in boxes:
                        if (float(px) - bx) ** 2 + (float(pz) - bz) ** 2 < 100 ** 2:
                            return True
                await asyncio.sleep(1.5)
        except Exception as e:
            logger.warning("[%s] Verify warehouse arrived error: %s", self.bot_id, e)
        return False

    def _get_restocker(self) -> ShulkerRestocker:
        """懒创建 ShulkerRestocker（寻路包装 allow_scaffold=False 防递归补货）。"""
        if self._restocker is None:
            async def _move_to_box(x: int, y: int, z: int) -> bool:
                return await self._move_to(x, y, z, max_offset=3,
                                           label=f"shulker({x},{y},{z})",
                                           timeout_ms=20000, allow_scaffold=False)
            self._restocker = ShulkerRestocker(
                mcp=self.mcp,
                check_inventory=self._check_inventory_level,
                move_to_cb=_move_to_box,
                activity_cb=self._activity,
                log_prefix=self.bot_id,
            )
        return self._restocker

    async def _ensure_food_offhand(self) -> bool:
        """确保副手 (slot 40 归一化 = 原始45) 有食物（猪排），没有则补货。

        返回 True 表示副手已有食物或补货成功，False 表示补货失败（不影响建造）。

        ⚠️ 2026-08-16 修复（用户实测死循环）：原 item_id 比较用 "minecraft:xxx" vs
        snapshot type（无前缀 "cooked_porkchop"）→ 永远不匹配 → 副手有猪排也检测不到
        → 反复补货。统一 _normalize_item_id 去前缀比较。
        """
        food_item = self._food_cfg.get("item_id", "minecraft:cooked_porkchop")
        food_norm = self._normalize_item_id(food_item)

        # 检查副手是否已有食物（slot 40 = 归一化后副手；type 已归一化为 name 无前缀）
        try:
            snap = await self.mcp.get_inventory_snapshot(inventory_id=0)
            items = (snap.get("data", snap)).get("items", [])
            for s in items:
                if s.get("slot") == 40:  # 前端归一化后副手=40
                    item_id = self._normalize_item_id(
                        (s.get("type", "") or "").split("[")[0])
                    if item_id == food_norm and s.get("count", 0) > 0:
                        return True
        except Exception:
            pass

        # 副手无食物 → 尝试从背包装备（装备后验证副手，防 Via 假成功）
        try:
            r = await self.mcp.equip_offhand(food_item)
            if r.get("success"):
                # 2026-08-16：equip 返回 success 但副手可能未同步（Via 延迟）——
                # 等 0.8s 再验证实际副手（避免"假装备"→下轮又补货）
                await asyncio.sleep(0.8)
                try:
                    snap2 = await self.mcp.get_inventory_snapshot(inventory_id=0)
                    items2 = (snap2.get("data", snap2)).get("items", [])
                    for s2 in items2:
                        if s2.get("slot") == 40 and self._normalize_item_id(
                                (s2.get("type", "") or "").split("[")[0]) == food_norm:
                            logger.info("[%s] Equipped %s to offhand from inventory",
                                        self.bot_id, food_item)
                            return True
                except Exception:
                    pass
                # 副手验证失败（可能装备到别的槽/物品不足）→ 继续走补货流程
                logger.warning("[%s] equip_offhand 返回成功但副手未检测到 %s（Via 同步延迟），重试装备",
                               self.bot_id, food_item)
                try:
                    r2 = await self.mcp.equip_offhand(food_item)
                    if r2.get("success"):
                        await asyncio.sleep(0.8)
                        try:
                            snap3 = await self.mcp.get_inventory_snapshot(inventory_id=0)
                            items3 = (snap3.get("data", snap3)).get("items", [])
                            for s3 in items3:
                                if s3.get("slot") == 40 and self._normalize_item_id(
                                        (s3.get("type", "") or "").split("[")[0]) == food_norm:
                                    return True
                        except Exception:
                            pass
                except Exception:
                    pass
        except Exception as e:
            logger.warning("[%s] equip_offhand %s failed: %s", self.bot_id, food_item, e)

        # 装备失败 → 先查背包是否有猪排：有则只差装备（等 Via 同步后重试），
        # 没有才去补货（防"背包有猪排却反复补货"循环）
        try:
            snap_b = await self.mcp.get_inventory_snapshot(inventory_id=0)
            items_b = (snap_b.get("data", snap_b)).get("items", [])
            for sb in items_b:
                if sb.get("slot") != 40 and self._normalize_item_id(
                        (sb.get("type", "") or "").split("[")[0]) == food_norm:
                    logger.info("[%s] 背包已有 %s，等待 Via 同步后重试装备副手",
                                self.bot_id, food_item)
                    return False  # 不补货（背包有猪排），等下轮监控重试装备
        except Exception:
            pass

        # 背包也没有 → 食物补货
        logger.info("[%s] 猪排不足，开始食物补货...", self.bot_id)
        if await self._do_food_restock():
            return await self._ensure_food_offhand()  # 递归一次（补货后再次装备）
        return False

    @_restock_serialized
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
            # 1. 保存当前位置（暂存 dth——取猪排后 /ehomes dth 传回建造点）
            # ⚠️ 2026-08-18 用户反馈"取猪排前为什么不先暂存当前位置"：逻辑已有，
            # 但缺 activity 日志用户看不到；补日志 + 保存失败直接中断（防返回错位）。
            self._activity("info",
                           f"暂存当前位置（{self._supply_cfg.get('save', '/esethomes dth')}）——取完猪排后传回此处")
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

            # 2026-08-16：睡觉请求优先——传送等待期间到达夜晚 → 提前让路（不寻路开箱），
            # 由主循环安全点响应睡觉；补货中断不视为失败（背包已有材料时下轮跳过补货）。
            if self._sleep_req.is_set():
                self._activity("info", "补货传送等待期间收到睡觉请求，中断补货让路睡觉")
                return False

            # 2026-08-16 用户反馈修复：传送后验证 bot 真的到了猪排仓库（末地）。
            # /ehomes zhurou 失败/未生效时 bot 还在主世界却去开末地盒子 → 补货失败。
            if not await self._verify_warehouse_arrived(boxes, timeout_s=10.0):
                self._activity("warn", "食物传送后未到仓库（维度/位置不符），重试传送一次")
                await self.mcp.send_chat(go_cmd)
                await asyncio.sleep(4.0)
                if not await self._verify_warehouse_arrived(boxes, timeout_s=10.0):
                    self._activity("warn", "食物重试传送后仍未到仓库，放弃本轮补货")
                    return False

            # 3. 按顺序尝试每个潜影盒坐标（先显式寻路触发 chunk 加载，再开箱）
            taken = False
            for bx, by, bz in boxes:
                # 开箱前再检查一次睡觉请求（寻路可能耗时，期间夜晚到达）
                if self._sleep_req.is_set():
                    self._activity("info", "开箱前检测到睡觉请求，中断补货让路睡觉")
                    return False
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

                    # 2026-08-16：睡觉中 → 本轮跳过（睡觉与补货都涉及传送/开箱，
                    # 且 bot 在床上，触发补货会把 bot 拉走）。睡醒后下轮再检查。
                    if self._sleeping:
                        continue
                    # 2026-08-16：睡觉请求已挂起（夜晚优先）→ 不触发补货，让位睡觉
                    if self._sleep_req.is_set():
                        continue

                    # 2026-08-16 溺水/坠落防护：血量持续下降且低（掉水淹死/虚空坠落）→
                    # 立即传送回建造点，避免死亡后复活到远处丢失位置
                    if health < 8 and self._last_health is not None and health < self._last_health:
                        self._activity("warn", f"血量持续下降（{self._last_health}→{health}），疑似溺水/坠落，传送回建造点")
                        await self._try_teleport_home("血量持续下降")
                        self._last_health = health
                        continue
                    # 2026-08-16 用户实测溺水掉线：单次血量极低（<4）立即传送——溺水/骷髅
                    # 连射可能在 2s 采样间隔内从高值直接打到低血，等"持续下降"来不及。
                    if health < 4:
                        self._activity("warn", f"血量过低（{health}），立即传送回建造点防死亡")
                        await self._try_teleport_home("血量过低")
                        self._last_health = health
                        continue
                    self._last_health = health

                    if food < threshold_food or health < threshold_health:
                        # 2026-08-16：补货失败冷却——上次补货失败后冷却期内不再重复触发
                        #（防「food低→补货→失败→food更低→再补货」死循环；盒子权限
                        # 未配置/寻路失败时尤其明显）
                        if time.monotonic() < self._food_restock_cooldown_until:
                            continue
                        self._activity("info", f"饱食度 {food}/血量 {health} 低，准备进食")
                        # 优先确保副手有食物
                        has_food = await self._ensure_food_offhand()
                        if not has_food:
                            # 补货失败 → 进入冷却（避免疯狂重试；权限/寻路修好后冷却自然过期）
                            self._food_restock_cooldown_until = (
                                time.monotonic() + self._food_restock_cooldown_s)
                            logger.warning("[%s] 食物不足且补货失败（food=%d, health=%d），"
                                           "进入 %ds 冷却",
                                           self.bot_id, food, health,
                                           int(self._food_restock_cooldown_s))
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

    async def force_sleep(self, timeout_s: float = 180.0) -> dict:
        """手动触发一次睡觉往返（2026-08-18 前端「睡觉按钮」入口）。

        复用夜晚自动睡觉的排队机制：set _sleep_req → 主循环在下一个安全点确认
        （_sleep_hold）暂停 → 执行 _do_sleep_cycle（保存位置→传床边→睡→天亮→传回）
        → 恢复建造。与 _sleep_monitor_loop 的请求串行（已有请求则拒绝重复）。
        返回 {success, reason}。
        """
        if not self._sleep_point:
            return {"success": False, "reason": "未配置睡觉点（任务或 bot 床坐标）"}
        if self._sleeping:
            return {"success": False, "reason": "bot 已在睡觉中"}
        if self._sleep_req.is_set():
            return {"success": False, "reason": "已有睡觉请求排队（夜晚自动/其他触发）"}
        self._activity("info", "手动触发睡觉（前端按钮）：请求主循环暂停去睡觉")
        self._sleep_req.set()
        try:
            await asyncio.wait_for(self._sleep_hold.wait(), timeout=timeout_s)
        except asyncio.TimeoutError:
            # 与 monitor 同款竞态防护：唤醒可能已阻塞的主循环
            self._sleep_req.clear()
            self._sleep_hold.clear()
            self._sleep_event.set()
            return {"success": False, "reason": "等待主循环暂停超时，未执行睡觉"}
        self._sleep_hold.clear()
        try:
            await self._do_sleep_cycle()
            return {"success": True, "reason": "睡觉往返完成"}
        except asyncio.CancelledError:
            raise
        except Exception as e:
            return {"success": False, "reason": f"睡觉执行异常：{e}"}
        finally:
            self._sleep_event.set()
            self._sleep_req.clear()
            self._sleep_hold.clear()

    async def _sleep_monitor_loop(self) -> None:
        """睡觉监控协程：轮询服务器时间，进入夜晚/雷暴可睡窗口 → 暂停建造去睡觉。

        与补货同款往返：保存当前位置(/esethomes dth) → 寻路到任务配置的床睡觉 →
        天亮醒来 → /ehomes dth 传回建造点 → 恢复建造。睡觉动作本身重置幻翼计时
        （即使服务器 doDaylightCycle=false 时间不跳，睡觉仍有效防幻翼）。

        防循环：一晚只睡一次（_slept_this_night）。doDaylightCycle=false 时间锁
        夜晚时，睡一次后跳过直到时间离开夜晚窗口（白天）才重置——避免"睡→醒→
        又检测到夜晚→再睡"死循环。
        维度检测（2026-08-16 用户反馈）：仅主世界可睡觉——末地/下界无昼夜循环
        （末地恒为"夜晚"时间），bot 补货时可能在末地仓库，若按 timeOfDay 判断会
        误触发睡觉且跨维度寻路失败（path_failed）。非主世界一律跳过。
        未配置睡觉点（任务 sleep_x/y/z 为空）→ 空转，不打扰建造。
        """
        if not self._sleep_point:
            return
        slept_this_night = False
        try:
            while not self._stopped:
                await asyncio.sleep(self._sleep_check_interval)
                if self._stopped or self._sleeping:
                    continue
                try:
                    st = await self.mcp.get_time_status()
                except Exception:
                    continue
                if not st.get("success"):
                    continue
                tod = st.get("time_of_day")
                if tod is None:
                    continue
                # 维度检测：仅主世界可睡觉（末地恒夜晚/下界床会爆炸）
                dim = st.get("dimension") or "unknown"
                if dim not in ("overworld", "minecraft:overworld", "minecraft_overworld"):
                    slept_this_night = True  # 非主世界视为"本晚已处理"，防每次循环误触
                    continue
                # 已在睡（如服务器自动入睡/外部触发）→ 等醒来流程由 _do_sleep_cycle 处理
                if st.get("is_sleeping"):
                    continue
                in_window = self._sleep_night_start <= tod <= self._sleep_night_end
                thunderstorm = bool(st.get("is_raining")) and int(st.get("thunder_state") or 0) > 0
                if not in_window and not thunderstorm:
                    slept_this_night = False  # 白天/非雷暴：重置"已睡"标记，等待下一晚
                    continue
                if slept_this_night:
                    continue  # 本晚已睡过（防 doDaylightCycle=false 锁夜晚死循环）
                # 2026-08-16 用户明确：补货中【不要】请求睡觉——补货（含拿猪排）在
                # 末地仓库，末地恒夜晚（doDaylightCycle=false），若按 timeOfDay 判断会
                # 误触发睡觉且跨维度寻路失败。补货是原子操作：要么补货前睡、要么
                # 补货后睡，绝不在补货中打断。_restock_lock 占用 = 补货中 → 本轮跳过。
                if self._restock_lock.locked():
                    continue
                slept_this_night = True
                self._activity("info",
                               f"检测到夜晚（timeOfDay={tod}），请求暂停建造去睡觉（床 "
                               f"{self._sleep_point}），防怪物攻击/幻翼")
                # 排队：通知主循环在下一个安全点暂停，等它确认（_sleep_hold）后再执行
                self._sleep_req.set()
                try:
                    # 2026-08-18：超时 60→120s——主循环可能在启动填坑/完成前补放/
                    # 大范围扫描等长操作中（实测补放 59 格耗时 81s），60s 内未到
                    # 安全点被误判超时 → 整晚不睡。120s 覆盖单次长操作边界。
                    await asyncio.wait_for(self._sleep_hold.wait(), timeout=120)
                except asyncio.TimeoutError:
                    # 主循环 120s 内未到达安全点（补货/移动卡住）→ 取消本次请求；
                    # ⚠️ 2026-08-18 竞态修复：必须 set _sleep_event——若主循环已在
                    # 安全点 clear _sleep_req + set _sleep_hold + await _sleep_event.wait()
                    # 而这里恰好超时放弃，主循环会永远等不到 _sleep_event → 卡死。
                    # set _sleep_event 让已阻塞的主循环恢复（未阻塞则无害）。
                    self._sleep_req.clear()
                    self._sleep_hold.clear()
                    self._sleep_event.set()
                    slept_this_night = False  # 允许下轮重试
                    self._activity("warn", "睡觉请求等待主循环暂停超时，本轮跳过")
                    continue
                self._sleep_hold.clear()
                try:
                    await self._do_sleep_cycle()
                except Exception as _sleep_cycle_err:
                    # 2026-08-16 修复：_do_sleep_cycle 异常必须在循环内捕获——
                    # 否则睡觉协程崩溃退出 → 整晚不再睡觉（用户实测夜晚不睡被怪物打）。
                    logger.error("[%s] do_sleep_cycle error: %s", self.bot_id, _sleep_cycle_err)
                    self._sleeping = False
                    self._sleep_event.set()
                    self._sleep_req.clear()
                    self._sleep_hold.clear()
        except asyncio.CancelledError:
            pass
        finally:
            self._sleeping = False
            self._sleep_event.set()

    async def _do_sleep_cycle(self) -> None:
        """执行一次完整睡觉往返（与补货同款传送方式）：

        暂停建造 → 保存当前位置(dth) → 寻路到床睡觉 → 睡足最短时长 → 等天亮/超时唤醒
        → /ehomes dth 传回建造点 → 恢复建造。任何一步失败都尽量恢复建造，不阻塞任务。

        用 _restock_lock 串行化：睡觉与补货都涉及传送/开箱，防并发互相打断
        （如食物监控在 bot 睡觉时触发补货把 bot 拉走）。
        """
        async with self._restock_lock:
            await self._do_sleep_cycle_locked()

    async def _do_sleep_cycle_locked(self) -> None:
        """睡觉往返实际执行（持锁版本，见 _do_sleep_cycle）。"""
        self._sleeping = True
        self._sleep_event.clear()
        try:
            # 1. 保存当前位置（补货同款：/esethomes dth）
            try:
                r = await self.mcp.send_chat(self._supply_cfg.get("save", "/esethomes dth"))
                if isinstance(r, dict) and r.get("success") is False:
                    self._activity("warn", f"睡觉前保存位置失败：{r.get('error', '?')}")
                else:
                    await asyncio.sleep(1.5)
            except Exception as e:
                logger.warning("[%s] Sleep save position error: %s", self.bot_id, e)

            # 2. 传送回初始点（用户需求：床在初始点附近，站初始点上面可直接点到；补货同款
            #    传送方式），再寻路到床睡觉（sleep_at 自带寻路保险：8 格内找床 → 寻路 → bot.sleep）
            sleep_go = (self._sleep_go_command
                        or self._supply_cfg.get("return_fixed")
                        or "/ehomes mapart").strip()
            try:
                self._activity("info", f"传送回初始点（{sleep_go}）准备睡觉")
                await self.mcp.send_chat(sleep_go)
                await asyncio.sleep(2.5)  # Via 传送后位置同步
            except Exception as e:
                logger.warning("[%s] Sleep go teleport error: %s", self.bot_id, e)
            try:
                sp = self._sleep_point
                result = await self.mcp.sleep_at(x=sp[0], y=sp[1], z=sp[2], timeout_ms=45000)
            except Exception as e:
                self._activity("warn", f"sleep_at 调用异常：{e}，跳过本轮睡觉")
                await self._return_from_sleep()
                return
            ok = bool(result.get("success"))
            reason = result.get("reason") or ""
            if not ok:
                # 2026-08-16：服务器 doDaylightCycle=false 时，玩家躺下会立即被唤醒
                # （时间不跳），mineflayer 报 "bot is not sleeping"——但睡眠动作已发生，
                # 幻翼计时已重置，视为完成。其它原因（床被占用/床边有怪物/床太远）则
                # 记日志。无论成功与否，bot 已走到床边，需传回建造点再恢复建造。
                self._activity("warn" if reason == "bot is not sleeping" else "warn",
                               f"睡觉结果：{reason}（doDaylightCycle=false 躺下即醒属正常，"
                               f"幻翼计时已重置）" if reason == "bot is not sleeping"
                               else f"睡觉失败（{reason}），传回建造点继续建造")
                await self._return_from_sleep()
                return

            # 3. 睡足最短时长（重置幻翼计时）
            await asyncio.sleep(self._sleep_min_sleep_s)
            self._activity("info", "已入睡，等待天亮")

            # 4. 等天亮（is_sleeping=false 或 时间离开夜晚窗口）；超时手动唤醒
            waited = 0.0
            while waited < self._sleep_max_wait_s:
                if self._stopped:
                    break
                await asyncio.sleep(5)
                waited += 5
                try:
                    st = await self.mcp.get_time_status()
                except Exception:
                    continue
                if not st.get("success"):
                    continue
                if not st.get("is_sleeping"):
                    break  # 已醒
                tod = st.get("time_of_day")
                if tod is not None and not (self._sleep_night_start <= tod <= self._sleep_night_end):
                    # 时间已离开夜晚窗口（天亮）但仍显示在睡 → 手动唤醒
                    try:
                        await self.mcp.wake_up()
                    except Exception:
                        pass
                    break
            else:
                # 超时未醒（doDaylightCycle=false 时间锁夜晚）→ 手动唤醒
                self._activity("warn", "等待天亮超时，手动唤醒")
                try:
                    await self.mcp.wake_up()
                except Exception:
                    pass

            # 5. 传回建造点（补货同款：/ehomes dth），等 Via 背包/位置同步
            await self._return_from_sleep()
            self._activity("info", "睡觉完成，已传回建造点，恢复建造")
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.warning("[%s] Sleep cycle error: %s", self.bot_id, e)
        finally:
            self._sleeping = False
            self._sleep_event.set()       # 恢复建造
            self._sleep_req.clear()       # 清理请求标记
            self._sleep_hold.clear()      # 清理确认标记

    async def _return_from_sleep(self) -> None:
        """睡觉往返后传回建造点（/ehomes dth，补货同款 return），等 Via 位置同步。"""
        try:
            await self.mcp.send_chat(self._supply_cfg.get("return", "/ehomes dth"))
            await asyncio.sleep(2.5)
        except Exception as e:
            logger.warning("[%s] Sleep return teleport error: %s", self.bot_id, e)
        self._last_pos = None  # 传送后位置未知，强制下次寻路