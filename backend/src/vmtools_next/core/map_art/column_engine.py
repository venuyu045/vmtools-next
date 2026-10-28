"""Column 引擎 —— 排级编队 + 列式推进（``build_mode="column"``，默认模式）。

编排模型（对齐任务文档）：
  1. 列池 ``_column_pool``：所有尚未建完的列号（0-based）
  2. 一排 = 取池中前 n 列（n = 当前活跃 bot 数），按序分给各 bot
  3. 开路 bot 先沿起始行铺 n 格「连接条」（让每台 bot 都有立足点）
  4. 各 bot 就位到本列连接条顶 → 广播开工 → 排内并行沿列推进
  5. 排尾同步（收齐 column_done）→ 完成列出池 → 蛇形掉头 → 下一排
  6. 减员/余列/运行中增减 bot 都通过「列池」自然收敛

⚠️ 2026-10-28 关键修复：旧实现列号是 1-based（``range(1, n+1)``）却直接
``world_x = origin_x + column_x``，导致整幅画向 +X/+Z 各偏移 1 格、第 0 列/行
永远不建。现在统一 0-based（见 ``types.py`` 坐标铁律）。
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Optional

from vmtools_next.adapters.abstract.bot_agent import AbstractBotAgent
from vmtools_next.core.map_art.base_coordinator import AIR, BaseCoordinator
from vmtools_next.core.map_art.geometry import column_cells
from vmtools_next.core.map_art.runtime import BotRuntime
from vmtools_next.core.map_art.types import (
    STATE_COMPLETED,
    STATE_FAILED,
    STATE_OFFLINE,
    STATE_PLACING,
    STATE_WAITING,
    ColumnRegion,
    SquadAssignment,
    SquadPlan,
    SquadState,
)

logger = logging.getLogger("vmtools.map_art.column")

# 透明格跨越用的临时方块候选（按优先级）
TEMP_BLOCK_CANDIDATES = (
    "minecraft:dirt", "minecraft:stone", "minecraft:cobblestone",
    "minecraft:oak_planks", "minecraft:spruce_planks",
)


class ColumnBuildLoop(BotRuntime):
    """单 bot 列式建造循环：一列接一列，排内并行。"""

    LEADER_BOT = "mf-001"

    def __init__(self, *args, column_region: ColumnRegion,
                 on_column_done: Optional[callable] = None,
                 on_bot_offline: Optional[callable] = None,
                 squad_lead: bool = False,
                 **kwargs):
        super().__init__(*args, **kwargs)
        self.column_region: ColumnRegion = column_region
        self.column_x: int = column_region.column_x
        self.squad_direction: int = column_region.direction
        self.squad_index: int = 1
        self.squad_start_z: int = column_region.z_start
        self.squad_end_z: int = column_region.z_end
        self.squad_lead: bool = squad_lead
        self._on_column_done = on_column_done
        self._on_bot_offline = on_bot_offline
        self._build_ready = asyncio.Event()
        self._squad_assigned = asyncio.Event()
        self._column_completed = False
        self._temp_blocks: list[tuple[int, int, int]] = []
        self._unit_done: set[tuple[int, int]] = set()   # 本 bot 生命周期内完成的 (x_rel, z_rel)
        self._sync_unit_totals()

    # ── 工作单元钩子 ──

    def work_bounds(self) -> tuple[int, int, int, int]:
        return self.column_region.bounds()

    def work_cells(self) -> list[tuple[int, int, str]]:
        return column_cells(self.block_matrix, self.column_region)

    def unit_label(self) -> str:
        return (f"列 {self.column_x}（世界 X={self.origin_x + self.column_x}）"
                f" z[{self.squad_start_z}..{self.squad_end_z}]")

    def resume_anchor(self) -> tuple[int, int, int]:
        z_anchor = self.squad_start_z - self.squad_direction
        return (self.origin_x + self.column_x,
                self.origin_y + self._stand_y_offset,
                self.origin_z + z_anchor)

    def status_extra(self) -> dict:
        return {
            "column": self.column_x,
            "world_x": self.origin_x + self.column_x,
            "squad_index": self.squad_index,
            "squad_direction": self.squad_direction,
        }

    def _sync_unit_totals(self) -> None:
        self.progress.blocks_total = sum(
            1 for (_x, _z), bid in self.block_matrix.items()
            if _x == self.column_x and bid and bid != AIR
            and self.squad_start_z <= _z <= self.squad_end_z)

    # ── 编队控制（协调器调用）──

    async def assign_squad(self, assignment: SquadAssignment, squad_index: int) -> None:
        self.column_region = assignment.to_column_region()
        self.column_x = self.column_region.column_x
        self.squad_direction = self.column_region.direction
        self.squad_start_z = self.column_region.z_start
        self.squad_end_z = self.column_region.z_end
        self.squad_index = squad_index
        self._column_completed = False
        self._build_ready.clear()
        self._sync_unit_totals()
        self._squad_assigned.set()

    async def signal_go(self) -> None:
        self._build_ready.set()

    async def wait_for_ready(self) -> bool:
        while not self._build_ready.is_set():
            if self.is_stopping():
                return False
            await asyncio.sleep(0.3)
        self._build_ready.clear()
        return True

    # ── 主循环 ──

    async def run(self) -> None:
        logger.info("[%s] column loop started: col=%d z[%d..%d] dir=%d",
                    self.bot_id, self.column_x, self.squad_start_z,
                    self.squad_end_z, self.squad_direction)
        self._activity("info", f"列式建造就绪：{self.unit_label()}")
        try:
            # 启动序列只做「定位/食物/睡觉/环境」，对账与补放由协调器任务级统一做
            await self.startup_sequence(reconcile=False)
            self._guard_task = asyncio.create_task(self.guard_monitor_loop())
            while not self.is_stopping():
                if not self._squad_assigned.is_set():
                    if not await self.wait_for_ready():
                        break
                self._squad_assigned.clear()
                if self.is_stopping():
                    break
                await self.build_column()
                if self.is_stopping():
                    break
                self._column_completed = True
                self.progress.state = STATE_WAITING
                if self._on_column_done:
                    try:
                        self._on_column_done(self.bot_id)
                    except Exception as e:
                        logger.warning("[%s] on_column_done error: %s", self.bot_id, e)
        except asyncio.CancelledError:
            self.progress.state = STATE_OFFLINE
        except Exception as e:
            self.progress.state = STATE_OFFLINE
            logger.error("[%s] column loop error: %s", self.bot_id, e)
            self._notify_offline(str(e))
        finally:
            await self.cleanup_tasks()
            if self._on_done:
                try:
                    self._on_done(self.bot_id)
                except Exception as e:
                    logger.warning("[%s] on_done error: %s", self.bot_id, e)

    # ── 单列建造 ──

    async def build_column(self) -> None:
        """沿本列建造方向逐格放置（边放边踩；透明格用临时方块跨越）。"""
        await self._paused.wait()
        if self.is_stopping():
            return
        self.progress.state = STATE_PLACING
        world_x = self.origin_x + self.column_x
        z_order = self.column_region.z_order()
        already = await self._load_placed_set()
        if already:
            self._unit_done |= already
            self.progress.blocks_placed = len(self._unit_done)

        placed = failed = gap = crossed = skipped = 0
        prev_z: Optional[int] = None
        for idx, z in enumerate(z_order):
            await self._paused.wait()
            if self._sleep_req.is_set():
                self._sleep_req.clear()
                self._sleep_event.clear()
                self._sleep_hold.set()
                await self._sleep_event.wait()
            if self.is_stopping():
                return
            self.progress.current_row = z
            world_z = self.origin_z + z
            block_id = self.block_matrix.get((self.column_x, z))
            is_air = (not block_id) or block_id == AIR

            # 站立点：首格站本格（协调器已就位在连接条上），之后站上一格顶
            stand = (world_x, self.origin_y + 1,
                     world_z if prev_z is None else self.origin_z + prev_z)
            st = await self.ensure_stand(stand, label=f"col-stand({self.column_x},{z})")
            if st == "gap":
                if not is_air:
                    self._pending_gaps.append((world_x, self.origin_y, world_z, block_id))
                    gap += 1
                self._activity("warn",
                               f"站立点 ({stand[0]},{stand[1]},{stand[2]}) 缺块，跳过 z={z}")
                continue
            if st == "fail":
                return

            if is_air:
                if idx == len(z_order) - 1:
                    continue  # 末格是空气 → 无需跨越
                if await self._cross_transparent(world_x, world_z, z):
                    prev_z = z
                    crossed += 1
                    continue
                # 跨越失败 → 本列剩余格不可达，全部记缺口后退出
                for z2 in z_order[idx:]:
                    bid2 = self.block_matrix.get((self.column_x, z2))
                    if bid2 and bid2 != AIR:
                        self._pending_gaps.append(
                            (world_x, self.origin_y, self.origin_z + z2, bid2))
                        gap += 1
                self._activity("warn",
                               f"透明格 ({world_x},{world_z}) 跨越失败（无临时方块），本列剩余 {gap} 格记缺口")
                break

            if (self.column_x, z) in already:
                # 断点续建：DB 已置位 → 不重复读/放，直接踩上
                prev_z = z
                skipped += 1
                continue

            res = await self.place_cell(self.column_x, z, block_id)
            if res.ok:
                self._mark_done(self.column_x, z)
                placed += 1
                prev_z = z
            else:
                failed += 1
                # prev_z 不更新：仍在上一格站立点

            await asyncio.sleep(self._column_place_interval)

        await self.flush_db(self.column_x)
        await self.reconcile_unit_end()
        self._activity("info",
                       f"列 x={self.column_x} 完成：新放 {placed} / 已建 {skipped} / "
                       f"失败 {failed} / 缺口 {gap} / 跨越 {crossed}（排 {self.squad_index}）")

    def _mark_done(self, x_rel: int, z_rel: int) -> None:
        self.progress.record_place()          # 速率统计
        self._unit_done.add((x_rel, z_rel))
        self.progress.blocks_placed = len(self._unit_done)

    async def _load_placed_set(self) -> set[tuple[int, int]]:
        """DB 中本列已置位的格（相对坐标），用于断点续建跳过。"""
        rows = self.store.query_cells(self._world_bounds(), placed_only=True)
        return {(x - self.origin_x, z - self.origin_z) for x, _y, z, _b, _v in rows}

    async def _cross_transparent(self, world_x: int, world_z: int, z_rel: int) -> bool:
        """透明格跨越：临时方块垫脚，踩上继续（任务结束时统一拆除）。"""
        chosen = None
        for tid in TEMP_BLOCK_CANDIDATES:
            if await self._ensure_item_in_hand(tid):
                chosen = tid
                break
        if chosen is None:
            return False
        if await self._place_with_retry(world_x, self.origin_y, world_z, chosen):
            self._temp_blocks.append((world_x, self.origin_y, world_z))
            self._activity("debug", f"透明格 ({world_x},{world_z}) 临时跨越")
            return True
        return False

    async def _dismantle_temp_blocks(self) -> None:
        """拆除本 bot 的临时跨越方块（逆序，保证始终有立足点）。"""
        if not self._temp_blocks:
            return
        self._activity("info", f"拆除 {len(self._temp_blocks)} 个临时跨越方块")
        for i in range(len(self._temp_blocks) - 1, -1, -1):
            wx, wy, wz = self._temp_blocks[i]
            if self.is_stopping():
                break
            try:
                mv = await self._move_to(wx, wy + 1, wz, max_offset=1,
                                         label=f"dismantle({wx},{wz})",
                                         timeout_ms=15000, verify_height=True)
                if not mv:
                    self._activity("warn", f"无法走到临时方块 ({wx},{wz})，跳过拆除")
                    continue
                await self.mcp.dig_block(wx, wy, wz)
                await asyncio.sleep(0.5)
            except Exception as e:
                logger.warning("[%s] dismantle (%d,%d,%d) error: %s", self.bot_id, wx, wy, wz, e)
        self._temp_blocks = []
        self._activity("info", "临时方块拆除完成")

    def _notify_offline(self, reason: str) -> None:
        if self._on_bot_offline:
            try:
                self._on_bot_offline(self.bot_id, reason)
            except Exception:
                pass


class MultiBotCoordinator(BaseCoordinator):
    """列式协作任务协调器（列池 + 排级编队 + 蛇形推进）。"""

    build_mode = "column"
    LEADER_BOT = ColumnBuildLoop.LEADER_BOT

    def __init__(self, task_id: str, projection_data: dict,
                 origin_x: int, origin_y: int, origin_z: int):
        super().__init__(task_id, projection_data, origin_x, origin_y, origin_z)
        self._squad = SquadState()
        self._column_pool: list[int] = list(range(self._size_x))
        self._squad_task: Optional[asyncio.Task] = None
        self._active_bot_ids: list[str] = []
        self._leader_id: str = self.LEADER_BOT
        self._build_active_sec: float = 0.0
        self._last_build_ts: float = 0.0
        self._connector_temps: list[tuple[int, int, int]] = []
        self._squad.offline_bots = []

    # ── 生命周期 ──

    async def start(self, bot_agents: dict[str, tuple[str, AbstractBotAgent]]) -> None:
        self._started_at = time.monotonic()
        self._squad.started_at = self._started_at
        self._squad.total_columns = self._size_x
        self._squad.total_rows = self._size_z
        if not bot_agents:
            logger.error("[%s] no bots available", self.task_id)
            return

        # 断点续建：用 DB 重建列池（只保留仍有未放置格的列）
        try:
            await self.load_progress()
            await self._rebuild_pool_from_db()
        except Exception as e:
            logger.warning("[%s] rebuild pool failed: %s", self.task_id, e)

        # bot 排序：开路者优先（其余保持传入顺序）
        bot_ids = list(bot_agents.keys())
        if self._leader_id in bot_ids:
            bot_ids.remove(self._leader_id)
            bot_ids.insert(0, self._leader_id)
        self._active_bot_ids = bot_ids
        self._squad.active_bots = list(bot_ids)

        for bot_id in bot_ids:
            bot_name, mcp = bot_agents[bot_id]
            await self.reset_bot_control(mcp)
            initial_col = self._column_pool[bot_ids.index(bot_id)] \
                if bot_ids.index(bot_id) < len(self._column_pool) else 0
            loop = self._make_loop(
                bot_id, bot_name, mcp, ColumnBuildLoop,
                column_region=ColumnRegion(initial_col, 0, self._size_z - 1, 1),
                on_column_done=self._on_column_done,
                on_bot_offline=self._on_bot_offline,
                squad_lead=(bot_id == self._leader_id),
            )
            self._loops[bot_id] = loop
            self._squad.bot_columns[bot_id] = initial_col
            asyncio.create_task(loop.run())

        self._squad_task = asyncio.create_task(self._squad_loop())
        self._start_push_loops()
        await self._emit_map_init(bot_agents, self._active_bot_ids, self._size_x, self._size_z)
        self._activity("info",
                       f"列式模式启动：{len(bot_ids)} bot / {self._size_x} 列 × "
                       f"{self._size_z} 行（{self._total_blocks} 块，待建 {len(self._column_pool)} 列）")

    async def _rebuild_pool_from_db(self) -> None:
        """用 DB 重建列池：仍有未放置格的列才需要建。"""
        pending_x = self.store.query_pending_columns(self._plane_world_bounds())
        if pending_x is None:
            return
        pool = [x - self.origin[0] for x in pending_x if 0 <= x - self.origin[0] < self._size_x]
        if pool:
            self._column_pool = sorted(pool)
            self._activity("info", f"断点续建：{len(self._column_pool)} 列仍有缺口（共 {self._size_x} 列）")

    # ── 排级主循环 ──

    async def _squad_loop(self) -> None:
        try:
            # 任务启动映射自检（四角测试方块，防镜像/旋转错位；失败只告警）
            try:
                await self._map_self_check()
            except Exception as e:
                logger.warning("[%s] map self-check error: %s", self.task_id, e)

            squad_index = 1
            direction = 1
            while not self._stopped_check():
                plan = self._plan_next_squad(squad_index, direction)
                if plan is None:
                    break
                self._squad.squad_index = plan.squad_index
                self._squad.direction = plan.direction
                self._squad.bot_done = set()
                self._squad.bot_columns = {a.bot_id: a.column_x for a in plan.assignments}
                self._activity(
                    "info",
                    f"排 {squad_index} 开始：列 {plan.col_start}..{plan.col_end}"
                    f"（0-based，世界 X={self.origin[0] + plan.col_start}.."
                    f"{self.origin[0] + plan.col_end}）方向 {'z+' if direction > 0 else 'z-'}"
                    f"，{len(plan.assignments)} bot，剩余 {len(self._column_pool)} 列")

                # 1) 开路者铺连接条
                await self._place_connector_row(plan)
                # 2) 各 bot 就位
                await self._position_bots(plan)
                # 3) 广播开工
                for a in plan.assignments:
                    loop = self._loops.get(a.bot_id)
                    if loop is not None:
                        await loop.signal_go()
                # 4) 排尾同步
                await self._wait_squad_done()
                # 5) 完成列出池
                self._retire_finished_columns(plan)
                # 6) 蛇形掉头 + 减员重组
                direction = -direction
                squad_index += 1
                if self._squad.offline_bots:
                    await self._reorganize_squad()
                await asyncio.sleep(0.8)   # 推进节流（防 bot 互相推挤）

            # 收尾：拆临时方块 → 任务级对账 + 自动补放 → 落库终态
            await self._dismantle_connector_temps()
            await self.finish_task(failed=bool(self._column_pool))
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error("[%s] squad loop error: %s", self.task_id, e)
            await self.finish_task(failed=True, reason=str(e))

    def _active_bots(self) -> list[str]:
        return [b for b in self._active_bot_ids
                if b not in self._squad.offline_bots and b in self._loops]

    def _plan_next_squad(self, squad_index: int, direction: int) -> Optional[SquadPlan]:
        """从列池取前 n 列组成一排；开路者拿最右列（铺完连接条就地就位）。"""
        active = self._active_bots()
        if not active or not self._column_pool:
            return None
        n = min(len(active), len(self._column_pool))
        cols = self._column_pool[:n]
        # 开路者排最后（拿最右列），其余按池顺序
        leader = self._leader_id if self._leader_id in active else None
        others = [b for b in active if b != leader]
        bots_order = (others + [leader])[:n] if leader else active[:n]
        z_start, z_end = (0, self._size_z - 1) if direction > 0 else (self._size_z - 1, 0)
        assignments = [
            SquadAssignment(bot_id=bots_order[i], column_x=cols[i],
                            direction=direction, z_start=z_start, z_end=z_end)
            for i in range(n)
        ]
        return SquadPlan(
            squad_index=squad_index, direction=direction, assignments=assignments,
            col_start=min(cols), col_end=max(cols),
            total_columns=self._size_x, total_rows=self._size_z,
            remaining_columns=len(self._column_pool),
            is_last=len(self._column_pool) <= n,
        )

    async def _place_connector_row(self, plan: SquadPlan) -> bool:
        """开路者沿起始行铺连接条（每列一格），让各 bot 有立足点。"""
        active = self._active_bots()
        connector_id = self._leader_id if self._leader_id in active else (active[0] if active else None)
        connector = self._loops.get(connector_id) if connector_id else None
        if connector is None:
            self._activity("warn", "无可用开路 bot，跳过连接条（各 bot 直接就位）")
            return False
        start_z = plan.assignments[0].z_start
        world_z = self.origin[2] + start_z
        ok = True
        for a in plan.assignments:
            world_x = self.origin[0] + a.column_x
            bid = self.block_matrix.get((a.column_x, start_z))
            is_temp = (not bid) or bid == AIR
            place_id = "minecraft:dirt" if is_temp else bid
            # 站到本格西侧（上一列顶 / 平台）
            mv = await connector._move_to(world_x - 1, self.origin[1] + 1, world_z,
                                          max_offset=1,
                                          label=f"connector({a.column_x},{start_z})",
                                          verify_height=True)
            if not mv:
                self._activity("warn",
                               f"开路 bot 无法走到列 {a.column_x} 西侧，连接条中断")
                ok = False
                break
            if not await connector._ensure_item_in_hand(place_id):
                self._activity("warn", f"开路 bot 缺少连接条材料 {place_id}")
                ok = False
                break
            if not await connector._place_with_retry(world_x, self.origin[1], world_z, place_id):
                self._activity("warn", f"连接条放置失败（列 {a.column_x}）")
                ok = False
                break
            if is_temp:
                self._connector_temps.append((world_x, self.origin[1], world_z))
            await asyncio.sleep(connector._column_place_interval)
        self._activity("info",
                       f"排 {plan.squad_index} 连接条{'完成' if ok else '部分失败'}"
                       f"（列 {plan.col_start}..{plan.col_end}）")
        return ok

    async def _position_bots(self, plan: SquadPlan) -> None:
        """各 bot 就位到本列连接条顶（分批，防互相推挤）。"""
        start_z = plan.assignments[0].z_start
        world_z = self.origin[2] + start_z
        ordered = sorted(plan.assignments,
                         key=lambda a: 0 if a.bot_id == self._leader_id else 1)
        for a in ordered:
            loop = self._loops.get(a.bot_id)
            if loop is None:
                continue
            await loop.assign_squad(a, plan.squad_index)
            world_x = self.origin[0] + a.column_x
            self._activity("info",
                           f"{a.bot_id} 就位 → 列 {a.column_x}（世界 X={world_x}, Z={world_z}）")
            try:
                ok = await loop._move_to(world_x, self.origin[1] + 1, world_z,
                                         max_offset=1,
                                         label=f"pos({a.bot_id},{a.column_x})",
                                         timeout_ms=30000, verify_height=True)
                if not ok:
                    await loop._try_teleport_home(f"就位失败重试({a.bot_id})")
                    ok = await loop._move_to(world_x, self.origin[1] + 1, world_z,
                                             max_offset=1,
                                             label=f"pos retry({a.bot_id})",
                                             timeout_ms=30000, verify_height=True)
                if not ok:
                    self._activity("warn",
                                   f"{a.bot_id} 就位失败（列 {a.column_x}），标记离线")
                    self._mark_offline(a.bot_id, "position_failed")
                    loop.progress.state = STATE_OFFLINE
            except Exception as e:
                logger.warning("[%s] position %s failed: %s", self.task_id, a.bot_id, e)
            await asyncio.sleep(0.6)

    async def _wait_squad_done(self, timeout: float = 7200.0) -> None:
        """排尾同步：等所有活跃 bot 上报列完成。"""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self._stopped_check():
                return
            active = self._active_bots()
            if not active:
                return
            if all(b in self._squad.bot_done for b in active):
                self._activity("info",
                               f"排 {self._squad.squad_index} 全部列完成（{len(active)} bot）")
                return
            # 检查离线（loop 自行判定 offline 且未上报）
            for b in active:
                loop = self._loops.get(b)
                if loop is not None and loop.progress.state == STATE_OFFLINE \
                        and b not in self._squad.bot_done:
                    self._mark_offline(b, "loop_offline")
            await asyncio.sleep(2)
        missing = [b for b in self._active_bots() if b not in self._squad.bot_done]
        if missing:
            self._activity("warn", f"排尾同步超时，标记离线：{missing}")
            for b in missing:
                self._mark_offline(b, "squad_timeout")

    def _retire_finished_columns(self, plan: SquadPlan) -> None:
        """把本排已完成的列从池中移除；未完成的列回到池首（下排重排）。"""
        finished: list[int] = []
        for a in plan.assignments:
            loop = self._loops.get(a.bot_id)
            done = (a.bot_id in self._squad.bot_done) and (
                loop is None or loop.progress.state != STATE_OFFLINE)
            if done and a.column_x in self._column_pool:
                finished.append(a.column_x)
        for col in finished:
            try:
                self._column_pool.remove(col)
            except ValueError:
                pass
        # 未完成（离线/超时）的列留在池里（天然回到池首附近）
        if finished:
            self._activity("info",
                           f"排 {plan.squad_index} 收尾：完成 {len(finished)} 列，"
                           f"剩余 {len(self._column_pool)} 列")

    # ── 回调 ──

    def _on_column_done(self, bot_id: str) -> None:
        self._squad.bot_done.add(bot_id)
        loop = self._loops.get(bot_id)
        if loop is not None:
            self._squad.placed_total = max(self._squad.placed_total,
                                           loop.progress.blocks_placed)

    def _on_bot_offline(self, bot_id: str, reason: str = "") -> None:
        self._mark_offline(bot_id, reason)

    def _mark_offline(self, bot_id: str, reason: str = "") -> None:
        if bot_id not in self._squad.offline_bots:
            self._squad.offline_bots.append(bot_id)
            self._activity("error", f"{bot_id} 离线（{reason}）→ 下一排减员重组")
        loop = self._loops.get(bot_id)
        if loop is not None:
            loop.progress.state = STATE_OFFLINE

    async def _reorganize_squad(self) -> None:
        """减员重组：把离线 bot 的未完成列放回池首，剩余 bot 继续。"""
        offline = [b for b in self._squad.offline_bots if b in self._loops]
        if not offline:
            return
        for bid in offline:
            loop = self._loops.get(bid)
            if loop is not None:
                try:
                    await loop.stop()
                except Exception:
                    pass
        remaining = [b for b in self._active_bot_ids if b not in self._squad.offline_bots]
        self._active_bot_ids = remaining
        self._squad.active_bots = list(remaining)
        self._activity("info",
                       f"减员重组：离线 {offline}，活跃 {remaining}（排宽 {len(remaining)}）")

    # ── 运行中增减 bot（用户需求：任何时候都能调整）──

    async def add_bot(self, bot_id: str, bot_name: str, mcp: AbstractBotAgent) -> bool:
        """新增 bot：下一排自动参与（列池里还有列时才有活干）。"""
        if bot_id in self._loops:
            return False
        if not self._column_pool:
            self._activity("warn", f"新增 bot {bot_id}：列池已空，无列可分配")
            return False
        await self.reset_bot_control(mcp)
        next_col = self._column_pool[0] if self._column_pool else 0
        loop = self._make_loop(
            bot_id, bot_name, mcp, ColumnBuildLoop,
            column_region=ColumnRegion(next_col, 0, self._size_z - 1, 1),
            on_column_done=self._on_column_done,
            on_bot_offline=self._on_bot_offline,
            squad_lead=False,
        )
        self._loops[bot_id] = loop
        if bot_id not in self._active_bot_ids:
            self._active_bot_ids.append(bot_id)
        if bot_id in self._squad.offline_bots:
            self._squad.offline_bots.remove(bot_id)
        self._squad.active_bots = list(self._active_bot_ids)
        asyncio.create_task(loop.run())
        self._activity("info",
                       f"新增 bot {bot_id}：下一排开始参与（剩余 {len(self._column_pool)} 列）")
        return True

    async def remove_bot(self, bot_id: str) -> bool:
        """移除 bot：停止其 loop，未完成的列回到列池（由其余 bot 接手）。"""
        loop = self._loops.get(bot_id)
        if loop is None:
            return False
        await loop.stop()
        col = getattr(loop, "column_x", None)
        if col is not None and loop.progress.state != STATE_COMPLETED \
                and col not in self._column_pool:
            self._column_pool.insert(0, col)
        self._loops.pop(bot_id, None)
        if bot_id in self._active_bot_ids:
            self._active_bot_ids.remove(bot_id)
        if bot_id in self._squad.bot_done:
            self._squad.bot_done.discard(bot_id)
        self._squad.active_bots = list(self._active_bot_ids)
        self._activity("info",
                       f"移除 bot {bot_id}：其列 {col} 回到列池（剩余 {len(self._column_pool)} 列）")
        return True

    async def stop(self) -> None:
        """停止任务：停 loop + 取消排级主循环（否则停止后编队仍在推进）。"""
        await super().stop()
        if self._squad_task is not None:
            try:
                self._squad_task.cancel()
            except Exception:
                pass
            self._squad_task = None

    # ── 状态 / 推送 / 断点 ──

    def _stopped_check(self) -> bool:
        if self._completion_notified:
            return True
        if not self._loops:
            return True
        if not self._active_bots():
            return True
        # 用户停止 / 全部 loop 已停止 → 编队退出
        return all(getattr(l, "is_stopping", lambda: False)() for l in self._loops.values())

    def _compute_status(self) -> str:
        if self._completion_notified:
            return TASK_COMPLETED
        if not self._column_pool and not self._active_bots():
            return TASK_FAILED if self._failed_loops else TASK_COMPLETED
        if self._squad.offline_bots and not self._active_bots():
            return TASK_FAILED
        if any(l.progress.state == STATE_WAITING for l in self._loops.values()):
            return "paused"
        return "running"

    def _squad_index(self) -> int:
        return self._squad.squad_index

    def _net_rate(self, placed: int, remaining: int, fallback: float) -> tuple[float, float]:
        now = time.monotonic()
        building = any(l.progress.state in ("placing", "moving") for l in self._loops.values())
        if building:
            if self._last_build_ts > 0:
                self._build_active_sec += max(0.0, now - self._last_build_ts)
            self._last_build_ts = now
        else:
            self._last_build_ts = now
        net_sec = self._build_active_sec
        if net_sec > 1:
            net_rate = placed / (net_sec / 60)
            return net_rate, (remaining / net_rate) * 60 if net_rate > 0 else 0.0
        return fallback, (remaining / fallback) * 60 if fallback > 0 else 0.0

    def _leader_loop(self):
        loop = self._loops.get(self._leader_id)
        if loop is not None and loop.progress.state != STATE_OFFLINE:
            return loop
        for b in self._active_bots():
            lp = self._loops.get(b)
            if lp is not None:
                return lp
        return next(iter(self._loops.values()), None)

    def _squad_payload(self) -> Optional[dict]:
        return {
            "task_id": self.task_id,
            "squad_index": self._squad.squad_index,
            "direction": self._squad.direction,
            "total_columns": self._size_x,
            "total_rows": self._size_z,
            "remaining_columns": len(self._column_pool),
            "offline_bots": list(self._squad.offline_bots),
            "columns": [{
                "bot_id": bid,
                "column_x": getattr(loop, "column_x", 0),
                "world_x": self.origin[0] + getattr(loop, "column_x", 0),
                "done": bid in self._squad.bot_done,
                "placed": loop.progress.blocks_placed,
                "total": loop.progress.blocks_total,
                "state": loop.progress.state,
            } for bid, loop in self._loops.items()],
        }

    def _progress_extra(self) -> dict:
        return {
            "squad_index": self._squad.squad_index,
            "direction": self._squad.direction,
            "column_pool": list(self._column_pool),
            "active_bots": list(self._active_bot_ids),
        }

    def _load_progress_extra(self, data: dict) -> None:
        try:
            if data.get("squad_index"):
                self._squad.squad_index = int(data["squad_index"])
            if data.get("direction"):
                self._squad.direction = int(data["direction"])
            pool = data.get("column_pool")
            if isinstance(pool, list) and pool:
                self._column_pool = [int(x) for x in pool]
        except Exception:
            pass

    # ── 收尾 ──

    async def _dismantle_connector_temps(self) -> None:
        """拆除连接条上的临时方块（air 列垫脚用）。"""
        if not self._connector_temps:
            return
        leader = self._leader_loop()
        if leader is None:
            return
        self._activity("info", f"拆除 {len(self._connector_temps)} 个连接条临时方块")
        for (wx, wy, wz) in reversed(self._connector_temps):
            try:
                await leader.mcp.dig_block(wx, wy, wz)
                await asyncio.sleep(0.4)
            except Exception as e:
                logger.warning("[%s] dismantle connector temp (%d,%d,%d) failed: %s",
                               self.task_id, wx, wy, wz, e)
        self._connector_temps = []

    # ── 映射自检 ──

    async def _map_self_check(self) -> bool:
        """四角测试方块读回校验（防镜像/旋转错误；失败只告警不阻断）。"""
        if not self._block_matrix:
            return False
        corners = [(0, 0), (self._size_x - 1, 0),
                   (0, self._size_z - 1), (self._size_x - 1, self._size_z - 1)]
        checks = [(cx, cz, self._block_matrix.get((cx, cz))) for cx, cz in corners]
        checks = [(cx, cz, bid) for cx, cz, bid in checks if bid and bid != AIR]
        if not checks:
            self._activity("info", "映射自检：四角无实心方块，跳过")
            return True
        leader = self._leader_loop()
        if leader is None:
            return False
        self._activity("info", f"映射自检：校验 {len(checks)} 个角（防镜像/旋转错误）")
        ok_count = 0
        for cx, cz, bid in checks:
            wx, wz = self.origin[0] + cx, self.origin[2] + cz
            try:
                actual = await leader.mcp.get_world_block_at(wx, self.origin[1], wz)
                name = ((actual.get("name") or "air").split("[")[0])
                if name not in ("air", "") and leader._normalize_item_id(name) \
                        != leader._normalize_item_id(bid):
                    self._activity(
                        "error",
                        f"映射自检失败：角 ({cx},{cz}) 期望 {bid.split(':')[-1]} 实际 {name}"
                        f"——可能存在镜像/旋转错误，请检查 origin 与 rotation")
                    return False
                ok_count += 1
            except Exception as e:
                logger.warning("[%s] self-check corner (%d,%d) failed: %s",
                               self.task_id, cx, cz, e)
        self._activity("info", f"映射自检通过（{ok_count}/{len(checks)} 角一致）")
        return True
