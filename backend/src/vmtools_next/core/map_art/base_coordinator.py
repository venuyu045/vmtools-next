"""BaseCoordinator —— 两套引擎（strip / column）共用的任务级编排。

重构前 ``MapArtCoordinator`` 与 ``MultiBotCoordinator`` 各写一份：配置加载、
活动日志、2D 矩阵、进度推送、初始地图推送、背包、生命周期、任务收尾。
本类收敛这些公共部分，子类只负责「怎么把 bot 编起来干活」：

  - ``StripBuildLoop``  → ``MapArtCoordinator``：分区独立
  - ``ColumnBuildLoop`` → ``MultiBotCoordinator``：排级编队

任务收尾（``finish_task``）在这里统一实现，包含 #51 要求的「缺块自动补放闭环」：
全量对账 → 补放 → 复对账，最多 ``auto_fix_max_rounds`` 轮。
"""

from __future__ import annotations

import asyncio
import logging
import time
import zlib
from typing import Optional

from vmtools_next.adapters.abstract.bot_agent import AbstractBotAgent
from vmtools_next.core.map_art.activity import ActivityLog
from vmtools_next.core.map_art.geometry import build_2d_matrix as _build_2d_matrix
from vmtools_next.core.map_art.geometry import resolve_size
from vmtools_next.core.map_art.settings import MapArtSettings
from vmtools_next.core.map_art.store import MapArtStore
from vmtools_next.core.map_art.types import (
    TASK_COMPLETED,
    TASK_FAILED,
    MapArtBuildState,
    ReconcileReport,
)

logger = logging.getLogger("vmtools.map_art.coordinator")

AIR = "minecraft:air"


def _sio():
    """延迟拿 Socket.IO 实例（测试环境无依赖时返回 None）。"""
    try:
        from vmtools_next.data.db import sio

        return sio
    except Exception:
        return None


class BaseCoordinator:
    """地图画任务级协调器基类。"""

    build_mode: str = "base"

    def __init__(self, task_id: str, projection_data: dict,
                 origin_x: int, origin_y: int, origin_z: int):
        self.task_id = task_id
        self.projection = projection_data or {}
        self.origin = (int(origin_x or 0), int(origin_y or 0), int(origin_z or 0))
        self.settings = MapArtSettings.load()
        self.store = MapArtStore(task_id)
        self.activity = ActivityLog(task_id)
        self._loops: dict = {}
        self._started_at: float = 0.0
        self._progress_task: Optional[asyncio.Task] = None
        self._checkpoint_task: Optional[asyncio.Task] = None
        self._completion_notified: bool = False
        self._done_loops: set[str] = set()
        self._failed_loops: set[str] = set()
        self._pending_regions: list = []

        # 投影 → 矩阵 / 尺寸（0-based 相对坐标）
        self._block_matrix: dict[tuple[int, int], str] = _build_2d_matrix(
            self.projection.get("layers", {}))
        self._size_x, self._size_z = resolve_size(self.projection, self._block_matrix)
        self._total_blocks: int = sum(
            1 for v in self._block_matrix.values() if v and v != AIR)

        # 任务级配置（DB 一次读完）
        cfg = self.store.load_task_config()
        self._supply_config: dict = cfg.get("supply_config") or self.settings.default_supply_config()
        self._supply_boxes: dict = cfg.get("supply_boxes") or {}
        self._food_config: dict = cfg.get("food_config") or self.settings.default_food_config()
        self._food_boxes: list = cfg.get("food_boxes") or []
        self._sleep_point: Optional[tuple[int, int, int]] = cfg.get("sleep_point")

    # ──────────────────────────────────────────
    # 子类钩子
    # ──────────────────────────────────────────

    async def start(self, bot_agents: dict[str, tuple[str, AbstractBotAgent]]) -> None:
        raise NotImplementedError

    async def add_bot(self, bot_id: str, bot_name: str, mcp: AbstractBotAgent):
        raise NotImplementedError

    async def remove_bot(self, bot_id: str) -> bool:
        raise NotImplementedError

    def _on_loop_done(self, bot_id: str) -> None:
        """单个 bot 收工回调（子类可扩展）。"""
        loop = self._loops.get(bot_id)
        self._done_loops.add(bot_id)
        # ⚠️ offline 也必须计入失败：bot 崩溃/被踢/卡死时 loop 状态是 offline，
        #   若只判 "failed" 会让「全员离线」被任务级判定成 completed。
        if loop is not None and loop.progress.state in ("failed", "offline"):
            self._failed_loops.add(bot_id)

    def _compute_status(self) -> str:
        if self._completion_notified:
            return TASK_COMPLETED
        if self._failed_loops:
            return TASK_FAILED
        if any(l.progress.state == "waiting" for l in self._loops.values()):
            return "paused"
        return "running"

    def _leader_loop(self):
        """挑一个还活着的 loop 做全图对账/补放（子类可覆盖优先顺序）。"""
        for loop in self._loops.values():
            if loop.progress.state != "offline":
                return loop
        return next(iter(self._loops.values()), None)

    def _squad_payload(self) -> Optional[dict]:
        """列式引擎的编队状态（strip 返回 None）。"""
        return None

    def _all_offline(self) -> bool:
        if not self._loops:
            return True
        return all(l.progress.state == "offline" for l in self._loops.values())

    # ──────────────────────────────────────────
    # 日志
    # ──────────────────────────────────────────

    def _activity(self, level: str, message: str) -> None:
        self.activity.push(level, message)

    def _on_loop_activity(self, bot_id: str, bot_name: str, level: str, message: str) -> None:
        self.activity.push(level, message, bot_id, bot_name)

    def emit_log_history(self) -> None:
        self.activity.emit_history()

    # ──────────────────────────────────────────
    # 兼容旧接口
    # ──────────────────────────────────────────

    @classmethod
    def build_2d_matrix(cls, layers: dict[int, list[tuple[int, int, int, str]]]):
        return _build_2d_matrix(layers)

    def _bot_sleep_point(self, bot_id: str):
        return self.store.bot_sleep_point(bot_id, self._sleep_point)

    def _make_loop(self, bot_id: str, bot_name: str, mcp: AbstractBotAgent,
                   loop_cls, **kwargs):
        """统一构造 loop（配置/日志/store 一处注入）。"""
        return loop_cls(
            bot_id=bot_id,
            bot_name=bot_name,
            task_id=self.task_id,
            block_matrix=self._block_matrix,
            origin_x=self.origin[0],
            origin_y=self.origin[1],
            origin_z=self.origin[2],
            mcp=mcp,
            settings=self.settings,
            store=self.store,
            activity=self.activity,
            supply_boxes=self._supply_boxes,
            supply_config=self._supply_config,
            food_config=self._food_config,
            food_boxes=self._food_boxes,
            sleep_point=self._bot_sleep_point(bot_id),
            on_done=self._on_loop_done,
            on_activity=self._on_loop_activity,
            **kwargs,
        )

    @staticmethod
    async def reset_bot_control(mcp: AbstractBotAgent) -> None:
        """复位手动控制状态（终端遗留方向键会与寻路抢控制 → 放置错位）。"""
        try:
            if hasattr(mcp, "cancel_pathing"):
                await mcp.cancel_pathing()
            if hasattr(mcp, "set_control_state"):
                for ctrl in ("forward", "back", "left", "right", "jump", "sneak", "sprint"):
                    await mcp.set_control_state(ctrl, False)
        except Exception as e:
            logger.warning("reset control state failed: %s", e)

    # ──────────────────────────────────────────
    # 生命周期
    # ──────────────────────────────────────────

    async def pause(self) -> None:
        for loop in self._loops.values():
            try:
                await loop.pause()
            except Exception:
                pass
        self._activity("info", "任务已暂停")

    async def resume(self) -> None:
        for loop in self._loops.values():
            try:
                await loop.resume()
            except Exception:
                pass
        self._activity("info", "任务已继续")

    async def stop(self) -> None:
        for loop in self._loops.values():
            try:
                await loop.stop()
            except Exception:
                pass
        for t in (self._progress_task, self._checkpoint_task):
            if t is not None:
                try:
                    t.cancel()
                except Exception:
                    pass
        self._progress_task = None
        self._checkpoint_task = None
        try:
            await self._persist_progress()
        except Exception:
            pass

    async def force_sleep(self, bot_id: str) -> dict:
        loop = self._loops.get(bot_id)
        if loop is not None:
            return await loop.force_sleep()
        return {"success": False,
                "reason": f"bot {bot_id} 不在任务 {self.task_id} 运行中"}

    async def get_bot_inventory(self) -> list[dict]:
        """任务内各 bot 的背包快照（前端背包面板轮询）。"""
        results: list[dict] = []
        for bot_id, loop in self._loops.items():
            try:
                snap = await loop.mcp.get_inventory_snapshot(inventory_id=0)
                items = (snap.get("data", snap)).get("items", [])
                parsed: list[dict] = []
                for s in items:
                    item_id = loop._normalize_item_id(s.get("type", ""))
                    cnt = s.get("count", 0)
                    if item_id and cnt > 0:
                        parsed.append({"name": item_id, "count": cnt})
                results.append({
                    "bot_id": bot_id,
                    "bot_name": loop.bot_name,
                    "items": parsed,
                    "total_items": sum(i["count"] for i in parsed),
                })
            except Exception as e:
                logger.warning("[%s] inventory snapshot for %s failed: %s",
                               self.task_id, bot_id, e)
                results.append({"bot_id": bot_id, "bot_name": loop.bot_name,
                                "items": [], "total_items": 0})
        return results

    # ──────────────────────────────────────────
    # 进度推送
    # ──────────────────────────────────────────

    def _start_push_loops(self) -> None:
        if self._progress_task is None:
            self._progress_task = asyncio.create_task(self._push_loop())
        if self._checkpoint_task is None:
            self._checkpoint_task = asyncio.create_task(self._checkpoint_loop())

    async def _push_loop(self) -> None:
        try:
            while True:
                await asyncio.sleep(2)
                try:
                    await self._push_progress()
                except Exception as e:
                    logger.warning("[%s] push progress failed: %s", self.task_id, e)
        except asyncio.CancelledError:
            pass

    async def _push_progress(self) -> None:
        sio = _sio()
        room = f"build_{self.task_id}"
        state = self._aggregate()
        if sio is not None:
            await sio.emit("build_progress", state.to_payload(), room=room)
            bots = [loop.bot_status() for loop in self._loops.values()]
            await sio.emit("build_bot_status",
                           {"task_id": self.task_id, "bots": bots}, room=room)
            squad = self._squad_payload()
            if squad is not None:
                await sio.emit("build_squad_status", squad, room=room)

    def _aggregate(self) -> MapArtBuildState:
        total = self._total_blocks or sum(
            l.progress.blocks_total for l in self._loops.values())
        placed = sum(l.progress.blocks_placed for l in self._loops.values())
        elapsed = max(0.0, time.monotonic() - self._started_at) if self._started_at else 0.0
        rate = placed / (elapsed / 60) if elapsed > 0 else 0.0
        remaining = max(0, total - placed)
        eta = (remaining / rate) * 60 if rate > 0 else 0.0
        net_rate, net_eta = self._net_rate(placed, remaining, rate)
        bots = [{
            "bot_id": l.bot_id,
            "name": l.bot_name,
            "state": l.progress.state,
            "placed": l.progress.blocks_placed,
            "total": l.progress.blocks_total,
            "current_row": l.progress.current_row,
            "rate": l.progress.place_rate,
            "blocks_placed": l.progress.blocks_placed,
            "blocks_total": l.progress.blocks_total,
            "place_rate": l.progress.place_rate,
            **{k: v for k, v in (l.status_extra() or {}).items()
               if k in ("column", "squad_index", "squad_direction")},
        } for l in self._loops.values()]
        return MapArtBuildState(
            task_id=self.task_id,
            status=self._compute_status(),
            total_blocks=total,
            placed_blocks=placed,
            bots=bots,
            materials={},
            elapsed_sec=elapsed,
            eta_sec=eta,
            net_rate=round(net_rate, 1),
            net_eta=net_eta,
            squad_index=self._squad_index(),
            build_mode=self.build_mode,
        )

    def _net_rate(self, placed: int, remaining: int, fallback: float) -> tuple[float, float]:
        """净速率（剔除补货/复位/等待）；strip 模式没有独立计时 → 回退整体速率。"""
        return fallback, (remaining / fallback) * 60 if fallback > 0 else 0.0

    def _squad_index(self) -> int:
        return 0

    async def _emit_map_init(self, bot_agents: dict, regions: list, size_x: int, size_z: int) -> None:
        """初始地图数据（历史协议，前端已不订阅，保留兼容）。"""
        sio = _sio()
        if sio is None:
            return
        blocks = [
            {"x": x, "y": self.origin[1], "z": z, "expected": bid, "placed": False}
            for (x, z), bid in self._block_matrix.items()
        ]
        bots = [{
            "bot_id": bid,
            "name": name,
            "color": f"#{zlib.crc32(bid.encode()) & 0xFFFFFF:06x}",
            "state": "idle",
        } for bid, (name, _mcp) in bot_agents.items()]
        await sio.emit("build_map_init", {
            "task_id": self.task_id,
            "blocks": blocks,
            "bots": bots,
            "origin": {"x": self.origin[0], "y": self.origin[1], "z": self.origin[2]},
            "size": {"x": size_x, "z": size_z},
            "build_mode": self.build_mode,
        }, room=f"build_{self.task_id}")

    # ──────────────────────────────────────────
    # 断点续建
    # ──────────────────────────────────────────

    async def _checkpoint_loop(self) -> None:
        try:
            interval = self.settings.checkpoint_interval_s
            while True:
                await asyncio.sleep(interval)
                try:
                    await self._persist_progress()
                except Exception as e:
                    logger.warning("[%s] checkpoint failed: %s", self.task_id, e)
        except asyncio.CancelledError:
            pass

    async def _persist_progress(self) -> None:
        payload = {
            "build_mode": self.build_mode,
            "size_x": self._size_x,
            "size_z": self._size_z,
            "placed_total": sum(l.progress.blocks_placed for l in self._loops.values()),
            "bots": {
                bid: {
                    "state": l.progress.state,
                    "placed": l.progress.blocks_placed,
                    **(l.status_extra() or {}),
                }
                for bid, l in self._loops.items()
            },
        }
        payload.update(self._progress_extra())
        self.store.save_progress(payload)

    def _progress_extra(self) -> dict:
        """子类附加的断点字段（列式：squad_index/direction/bot_columns）。"""
        return {}

    async def load_progress(self) -> Optional[dict]:
        data = self.store.load_progress()
        if data:
            self._load_progress_extra(data)
        return data

    def _load_progress_extra(self, data: dict) -> None:
        pass

    # ──────────────────────────────────────────
    # 任务级对账 + 缺块自动补放（#51 闭环）
    # ──────────────────────────────────────────

    def _plane_world_bounds(self) -> tuple[int, int, int, int]:
        return (self.origin[0], self.origin[0] + self._size_x - 1,
                self.origin[2], self.origin[2] + self._size_z - 1)

    async def reconcile_task(self, *, scan: bool = True) -> tuple[int, int, int]:
        """全图对账 → (漏放数, 错色数, 检查总数)。

        按 128×128 瓦片分块（大图不一次性拉全表，内存与 WS 帧都可控）：
          - DB 里 ``placed=False`` 的期望格直接算漏放（不浪费 WS 往返）
          - 已置位的格做真实世界复核（未加载 chunk 不判缺口）
        """
        from vmtools_next.core.map_art.geometry import tile_ranges

        x_min, x_max, z_min, z_max = self._plane_world_bounds()
        missing = wrong = checked = 0
        for (x0, x1) in tile_ranges(x_min, x_max):
            for (z0, z1) in tile_ranges(z_min, z_max):
                bounds = (x0, x1, z0, z1)
                expected = self.store.query_expected(bounds)
                if not expected:
                    continue
                placed_rows = self.store.query_cells(bounds, placed_only=True)
                placed_keys = {(x, y, z) for x, y, z, _b, _v in placed_rows}
                unplaced = [e for e in expected if (e[0], e[1], e[2]) not in placed_keys]
                checked += len(expected)
                missing += len(unplaced)
                leader = self._leader_loop()
                if leader is None:
                    continue
                if unplaced:
                    leader._pending_gaps.extend(unplaced)
                if placed_rows:
                    rep = await leader.reconcile_cells(
                        [(x, y, z, b) for x, y, z, b, _v in placed_rows],
                        "任务对账", scan=scan)
                    missing += rep.missing
                    wrong += rep.wrong
        self._activity("info",
                       f"全图对账：检查 {checked} 格 / 漏放 {missing} / 错色 {wrong}")
        return missing, wrong, checked

    async def auto_fix(self) -> int:
        """缺块自动补放（#51）：对 pending_gaps 逐格补放，最多 N 轮。"""
        leader = self._leader_loop()
        if leader is None:
            return 0
        total_filled = 0
        rounds = max(0, self.settings.auto_fix_max_rounds)
        for i in range(rounds):
            if not leader._pending_gaps:
                break
            self._activity("info",
                           f"自动补放第 {i + 1}/{rounds} 轮：待补 {len(leader._pending_gaps)} 格")
            try:
                filled = await leader._fill_pending_gaps()
            except Exception as e:
                logger.warning("[%s] auto fix round %d failed: %s", self.task_id, i + 1, e)
                break
            total_filled += filled
            if filled == 0:
                break
        if total_filled:
            self._activity("info", f"自动补放完成：补 {total_filled} 格，剩余待补 "
                                   f"{len(leader._pending_gaps)} 格")
        return total_filled

    async def finish_task(self, failed: bool = False, reason: str = "",
                          *, reconcile: bool = True) -> None:
        """任务收尾：对账 → 缺块自动补放 → 复对账 → 落库终态 → 推送。

        终态判定铁律：**只要还有缺口就不能写 completed**。
        三种「没建完」都要判 failed：
          ① 调用方显式 ``failed=True``（编队异常/用户停止）
          ② 全图对账后仍有漏放/错色
          ③ Bot 全员离线（此时不可能建完，且逐格对账会把已结束的任务拖死）
        """
        if self._completion_notified:
            return
        self._completion_notified = True
        missing = wrong = 0
        all_offline = self._all_offline()
        try:
            if reconcile and not all_offline:
                missing, wrong, _checked = await self.reconcile_task()
                if self.settings.auto_fix_enabled and (missing or wrong):
                    self._activity("info", "存在缺口，启动自动补放闭环")
                    await self.auto_fix()
                    missing, wrong, _checked = await self.reconcile_task()
            elif all_offline:
                self._activity("warn",
                               f"Bot 全员离线，跳过全图对账{('：' + reason) if reason else ''}")

            if all_offline:
                final_failed = True
                if not reason:
                    reason = "Bot 全员离线，任务未建完"
            elif missing or wrong:
                final_failed = True
                if not reason:
                    reason = f"对账后仍有 {missing} 格漏放 / {wrong} 格错色"
            else:
                final_failed = bool(failed)

            # 各 bot 传送回兜底位置（尽力而为，不影响状态判定）
            for loop in self._loops.values():
                try:
                    await loop._send_teleport(
                        loop._supply_cfg.get("return_fixed", "/ehomes mapart"))
                except Exception:
                    pass

            self.store.persist_status(
                TASK_FAILED if final_failed else TASK_COMPLETED,
                reason if final_failed else "")
            self._activity(
                "error" if final_failed else "info",
                f"任务结束：{'失败' if final_failed else '完成'}"
                + (f"（{reason}）" if reason else ""))
            await self._emit_final(final_failed, reason)
            self._notify_scheduler()
        except Exception as e:
            logger.error("[%s] finish_task failed: %s", self.task_id, e)

    async def _emit_final(self, failed: bool, reason: str) -> None:
        sio = _sio()
        if sio is None:
            return
        try:
            await sio.emit("build_progress",
                           {"task_id": self.task_id,
                            "status": TASK_FAILED if failed else TASK_COMPLETED,
                            "error_message": reason},
                           room=f"build_{self.task_id}")
        except Exception:
            pass

    def _notify_scheduler(self) -> None:
        """任务结束 → 广播队列 + 触发下一个排队任务（不阻塞收尾）。"""
        try:
            from vmtools_next.core.task_scheduler import get_task_scheduler

            sched = get_task_scheduler()
            if sched:
                asyncio.create_task(sched.broadcast_queue())
                asyncio.create_task(sched.schedule_once())
        except Exception as e:
            logger.debug("[%s] notify scheduler failed: %s", self.task_id, e)

    # ──────────────────────────────────────────
    # 工具
    # ──────────────────────────────────────────

    @property
    def loops(self) -> dict:
        return self._loops

    @property
    def block_matrix(self) -> dict[tuple[int, int], str]:
        return self._block_matrix

    @property
    def size(self) -> tuple[int, int]:
        return (self._size_x, self._size_z)

    def describe(self) -> str:
        return (f"{self.build_mode} {self._size_x}×{self._size_z} "
                f"blocks={self._total_blocks} bots={len(self._loops)}")
