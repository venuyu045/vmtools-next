"""Strip 引擎 —— 分区独立 + 行式蛇形（``build_mode="strip"``，旧模式保留）。

每个 bot 拿一条 Z 方向条带，覆盖完整 X；bot 站行北缘（z-1）向南铺，行内蛇形
（正向行 x 升序、反向行降序，行间只移动 1 格）。

与重构前 ``BotBuildLoop.run`` 的区别：
  - 启动序列/对账/放置语义全部来自 ``BotRuntime``（无复制粘贴）
  - ``_place_row`` 只剩「遍历顺序 + 站立点推导」，放置语义走 ``place_cell``
  - 区域完成判定改为「真实世界对账」+ 任务级自动补放（#51）
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Optional

from vmtools_next.adapters.abstract.bot_agent import AbstractBotAgent
from vmtools_next.core.map_art.base_coordinator import AIR, BaseCoordinator
from vmtools_next.core.map_art.geometry import partition_rectangular
from vmtools_next.core.map_art.runtime import BotRuntime
from vmtools_next.core.map_art.types import (
    STATE_COMPLETED,
    STATE_FAILED,
    STATE_OFFLINE,
    STATE_PLACING,
    STATE_WAITING,
    Region,
)

logger = logging.getLogger("vmtools.map_art.strip")


class StripBuildLoop(BotRuntime):
    """单 bot 行式蛇形建造循环（strip 模式）。"""

    def __init__(self, *args, region: Region, **kwargs):
        super().__init__(*args, **kwargs)
        self.region: Region = region
        self.progress.blocks_total = sum(
            1 for (x, z), bid in self.block_matrix.items()
            if self.region.contains(x, z) and bid and bid != AIR)

    # ── 工作单元钩子 ──

    def work_bounds(self) -> tuple[int, int, int, int]:
        return self.region.bounds()

    def work_cells(self) -> list[tuple[int, int, str]]:
        from vmtools_next.core.map_art.geometry import region_cells

        return region_cells(self.block_matrix, self.region)

    def unit_label(self) -> str:
        return f"区域 z[{self.region.z_start}..{self.region.z_end}]"

    def resume_anchor(self) -> tuple[int, int, int]:
        return (self.origin_x + self.region.x_start,
                self.origin_y + self._stand_y_offset,
                self.origin_z + self.region.z_start - 1)

    def status_extra(self) -> dict:
        return {
            "region": {
                "x_start": self.region.x_start + self.origin_x,
                "x_end": self.region.x_end + self.origin_x,
                "z_start": self.region.z_start + self.origin_z,
                "z_end": self.region.z_end + self.origin_z,
            },
        }

    # ── 行内顺序 ──

    def _row_is_forward(self, row_z: int) -> bool:
        """偶数相对行正向（x 升序），奇数行反向（蛇形，省掉回程）。"""
        return (row_z - self.region.z_start) % 2 == 0

    def _row_x_span(self, row_z: int) -> list[int]:
        xs = list(range(self.region.x_start, self.region.x_end + 1))
        return xs if self._row_is_forward(row_z) else xs[::-1]

    def _stand_y_for_row(self, row_z: int) -> int:
        """行首站立高度：第一行站平台顶，后续行站上一行方块顶。"""
        if row_z > self.region.z_start:
            return self.origin_y + 1
        return self.origin_y + self._stand_y_offset

    async def _move_to_row_edge(self, row_z: int) -> bool:
        """移动到行北缘（行首 x 的 z-1 处）。"""
        xs = self._row_x_span(row_z)
        target_x = self.origin_x + (xs[0] if xs else self.region.x_start)
        target_z = self.origin_z + row_z - 1
        ok = await self._move_to(target_x, self._stand_y_for_row(row_z), target_z,
                                 max_offset=1, label=f"row {row_z} edge",
                                 timeout_ms=20000, verify_height=True)
        if not ok:
            self.progress.state = STATE_OFFLINE
        return ok

    # ── 主循环 ──

    async def run(self) -> None:
        logger.info("[%s] strip loop started: rows %d→%d",
                    self.bot_id, self.region.z_start, self.region.z_end)
        self._activity("info", f"开始建造{self.unit_label()}")
        try:
            resume_z, resume_x = await self._restore_progress()
            await self.startup_sequence()
            self._guard_task = asyncio.create_task(self.guard_monitor_loop())

            for row_z in range(resume_z, self.region.z_end + 1):
                if self.is_stopping():
                    break
                # 睡觉请求 → 暂停建造（安全点：行循环开头）
                if self._sleep_req.is_set():
                    self._sleep_req.clear()
                    self._sleep_event.clear()
                    self._sleep_hold.set()
                    await self._sleep_event.wait()
                if self.is_stopping():
                    break

                self.progress.current_row = row_z
                world_z = self.origin_z + row_z

                # 每行开始前确认还在建造区（死亡复活/被传送走 → 直接拉回）
                try:
                    p = await self._get_player_pos()
                    if p and not self._near_build_area(p[0], p[1]):
                        self._activity("warn",
                                       f"bot 不在建造区域（{p[0]:.0f},{p[1]:.0f}），主动传送回建造点")
                        await self._try_teleport_home("bot 不在建造区域")
                except Exception:
                    pass

                if not await self._move_to_row_edge(row_z):
                    if self.is_stopping():
                        break
                    await self._try_teleport_home("行边缘寻路失败")
                    if not await self._move_to_row_edge(row_z):
                        break

                await self._place_row(row_z, world_z,
                                      start_x=resume_x if row_z == resume_z else None)
                if self.progress.state == STATE_OFFLINE:
                    break

            if not self.is_stopping():
                await self._finalize_region()
        except asyncio.CancelledError:
            self.progress.state = STATE_OFFLINE
        except Exception as e:
            self.progress.state = STATE_OFFLINE
            logger.error("[%s] strip loop error: %s", self.bot_id, e)
        finally:
            await self.cleanup_tasks()
            if self._on_done:
                try:
                    self._on_done(self.bot_id)
                except Exception as e:
                    logger.warning("[%s] on_done callback error: %s", self.bot_id, e)

    async def _finalize_region(self) -> None:
        """区域收尾：补放缺口 → 完成前对账 → 判定区域终态。"""
        if self._pending_gaps:
            filled = await self._fill_pending_gaps()
            if filled > 0:
                self._activity("info", f"补放破洞 {filled} 格，重新对账")
        ok, pending = await self.reconcile_final()
        if pending > 0:
            # 给服务器同步一次机会后复对账（Via 客户端数据滞后）
            await asyncio.sleep(3)
            ok, pending = await self.reconcile_final()
        self.progress.blocks_placed = ok
        total = self.progress.blocks_total
        if pending > 0:
            self.progress.state = STATE_FAILED
            self._activity("error",
                           f"区域结束仍有 {pending} 块未确认，按 {ok}/{total} 记录")
        elif total > 0 and ok < total:
            self.progress.state = STATE_FAILED
            self._activity("error", f"区域完成但未放完：{ok}/{total} 方块")
        else:
            self.progress.state = STATE_COMPLETED
            self._activity("info", f"区域完成：{ok} 方块")

    # ── 单行放置（放置语义走 place_cell）──

    async def _place_row(self, row_z: int, world_z: int,
                         start_x: Optional[int] = None) -> None:
        await self._paused.wait()
        if self.is_stopping():
            return

        x_span = self._row_x_span(row_z)
        if start_x is not None:
            if self._row_is_forward(row_z):
                x_span = [x for x in x_span if x >= start_x]
            else:
                x_span = [x for x in x_span if x <= start_x]
        self.progress.state = STATE_PLACING
        first_stand_y = self._stand_y_for_row(row_z)
        stand: Optional[tuple[int, int, int]] = None
        placed = failed = gap = 0

        for x in x_span:
            await self._paused.wait()
            if self._sleep_req.is_set():
                self._sleep_req.clear()
                self._sleep_event.clear()
                self._sleep_hold.set()
                await self._sleep_event.wait()
            if self.is_stopping():
                return

            block_id = self.block_matrix.get((x, row_z))
            if not block_id or block_id == AIR:
                continue  # 空白格不放置、不消耗站立点

            world_x = self.origin_x + x
            if stand is None:
                if start_x is not None and x == start_x:
                    stand = (world_x, self.origin_y + 1, world_z)   # 断点格方块顶
                else:
                    stand = (world_x, first_stand_y, world_z - 1)   # 行北缘

            st = await self.ensure_stand(stand, label=f"stand({world_x},{world_z})")
            if st == "gap":
                self._pending_gaps.append((world_x, self.origin_y, world_z, block_id))
                gap += 1
                self._activity("warn",
                               f"站立点 ({stand[0]},{stand[1]},{stand[2]}) 缺块，跳过 ({world_x},{world_z})")
                continue
            if st == "fail":
                return

            res = await self.place_cell(x, row_z, block_id)
            if res.ok:
                placed += 1
                stand = (world_x, self.origin_y + 1, world_z)   # 边放边踩
            else:
                failed += 1
                # stand 不更新：仍在上一个站立点

            self._place_sample_count += 1
            if self._place_sample_count % 10 == 0:
                await self._update_place_interval()
            await asyncio.sleep(self._place_interval)

        await self.flush_db(row_z)
        await self.reconcile_unit_end()
        if placed or failed or gap:
            self._activity("info",
                           f"第 {row_z} 行：成功 {placed} / 失败 {failed} / 缺站立 {gap}")
        if row_z == self.region.z_start or row_z % 10 == 0 or row_z == self.region.z_end:
            self._activity("info", f"第 {row_z} 行完成")

    # ── 断点续建 ──

    async def _restore_progress(self) -> tuple[int, Optional[int]]:
        """从 DB 恢复 (起始行, 起始列)；无记录则从区域首行开始。"""
        try:
            rows = self.store.query_cells(self._world_bounds(), placed_only=True)
            if rows:
                max_wz = max(r[2] for r in rows)
                row_z = max(self.region.z_start,
                            min(max_wz - self.origin_z, self.region.z_end))
                xs = [r[0] - self.origin_x for r in rows if r[2] == max_wz]
                resume_x: Optional[int] = None
                if xs:
                    resume_x = max(xs) if self._row_is_forward(row_z) else min(xs)
                self.progress.current_row = row_z
                self._activity(
                    "info",
                    f"断点续建：从第 {row_z} 行"
                    + (f" 第 {resume_x} 列继续" if resume_x is not None else " 行首继续")
                    + f"（跳过 {row_z - self.region.z_start} 个已建行）")
                return row_z, resume_x
        except Exception as e:
            logger.warning("[%s] restore progress failed: %s", self.bot_id, e)
        return self.region.z_start, None


class MapArtCoordinator(BaseCoordinator):
    """strip 模式任务协调器：分区 → 每 bot 独立 loop → 全部结束判定终态。"""

    build_mode = "strip"

    async def start(self, bot_agents: dict[str, tuple[str, AbstractBotAgent]]) -> None:
        self._started_at = time.monotonic()
        n = len(bot_agents)
        if n == 0:
            logger.error("[%s] no bots available", self.task_id)
            return
        regions = partition_rectangular(self._size_x, self._size_z, n)
        bot_ids = list(bot_agents.keys())
        for i, region in enumerate(regions):
            bot_id = bot_ids[i]
            bot_name, mcp = bot_agents[bot_id]
            await self.reset_bot_control(mcp)
            loop = self._make_loop(bot_id, bot_name, mcp, StripBuildLoop, region=region)
            self._loops[bot_id] = loop
            asyncio.create_task(loop.run())
        self._start_push_loops()
        await self._emit_map_init(bot_agents, regions, self._size_x, self._size_z)
        self._activity("info",
                       f"strip 模式启动：{len(self._loops)} bot / "
                       f"{self._size_x}×{self._size_z}（{self._total_blocks} 块）")

    # ── 运行中增减 bot（P2-27 区域接管）──

    async def add_bot(self, bot_id: str, bot_name: str, mcp: AbstractBotAgent):
        """把待接管区域分配给新 bot；无待接管区域返回 None。"""
        if not self._pending_regions:
            self._activity("warn", f"新增 bot {bot_id}：没有待接管区域（全部已分配）")
            return None
        region = self._pending_regions.pop(0)
        await self.reset_bot_control(mcp)
        loop = self._make_loop(bot_id, bot_name, mcp, StripBuildLoop, region=region)
        self._loops[bot_id] = loop
        self._done_loops.discard(bot_id)
        asyncio.create_task(loop.run())
        self._activity("info",
                       f"bot {bot_id} 接管区域 z[{region.z_start}..{region.z_end}]")
        return region

    async def remove_bot(self, bot_id: str) -> bool:
        loop = self._loops.pop(bot_id, None)
        if loop is None:
            return False
        await loop.stop()
        self._done_loops.discard(bot_id)
        if loop.progress.state != STATE_COMPLETED:
            self._pending_regions.append(loop.region)
            self._activity("info",
                           f"bot {bot_id} 已移除，区域 z[{loop.region.z_start}.."
                           f"{loop.region.z_end}] 进入待接管队列")
        else:
            self._activity("info", f"bot {bot_id} 已移除（其区域已完成）")
        return True

    # ── 完成判定 ──

    def _on_loop_done(self, bot_id: str) -> None:
        super()._on_loop_done(bot_id)
        if self._completion_notified or not self._loops:
            return
        if len(self._done_loops) >= len(self._loops):
            asyncio.create_task(self.finish_task(
                failed=bool(self._failed_loops),
                reason=(f"{len(self._failed_loops)} 个 Bot 区域未完成" if self._failed_loops else "")))

    def _compute_status(self) -> str:
        if self._completion_notified:
            return "completed"
        if self._failed_loops:
            return STATE_FAILED
        if self._done_loops and self._loops and len(self._done_loops) >= len(self._loops):
            return STATE_COMPLETED
        if any(l.progress.state == STATE_WAITING for l in self._loops.values()):
            return "paused"
        return "running"
