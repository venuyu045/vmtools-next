"""Auto Sleep Plugin — 永昼：夜晚自动到固定睡觉点睡觉，跳过黑夜（2026-08-16）。

原理（服务器已确认「只要一个玩家睡觉即可跳过夜晚」）::

    夜晚（timeOfDay ∈ [night_start_tick, night_end_tick]）且 bot 空闲时，
    bot 寻路到「固定睡觉点」（前端「功能」tab 配置，mcc_bots.sleep_x/y/z，
    即床的方块坐标）→ 右键床睡觉 → 服务器跳过夜晚（时间跳到白天）→
    天亮自动醒来 → 可选返回睡觉前位置 → 实现服务器「永昼」。

决策在 Python 端（与 auto_afk 等插件同构），原子操作在 Node 端
（handlers/sleep.js：get_time_status / sleep_at / wake_up）。

冲突规避（skip_when_busy=True 时）：
- 手动标记「工作中」（任务管理页）
- 物流 run（running/paused）
- 地图画 assignment（任务运行中）
- 仓库扫描（queued/running）
- 战斗模式开启（auto-attack / guard）
以上任一 → 本轮跳过（不打断任务）。

仅主世界可睡觉：下界/末地直接跳过。
服务器关闭昼夜循环（doDaylightCycle=false）时睡觉不会跳时间 → 记录并跳过。

配置（经 plugin_states 持久化）::

    {"check_interval_s": 20, "night_start_tick": 13000, "night_end_tick": 23000,
     "return_after_sleep": true, "skip_when_busy": true}

per-bot 启停走 plugin_bot_states（前端「功能」tab 开关）。
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Optional

from vmtools_next.infra.logging import get_logger
from vmtools_next.plugins.base import IPlugin, PluginContext

logger = get_logger("plugins.auto_sleep")

# 主世界维度标识（minecraft 协议 dimension 字段值）
_OVERWORLD = ("overworld", "minecraft:overworld", "minecraft_overworld")


class Plugin(IPlugin):
    """MF 永昼插件：夜晚自动到固定睡觉点睡觉，跳过黑夜。"""

    name = "auto_sleep"
    version = "1.0.0"
    engine = "mineflayer"
    description = "永昼：夜晚自动到固定睡觉点睡觉，跳过黑夜（服务器一人睡即跳夜）"

    default_config = {
        "check_interval_s": 20,
        "night_start_tick": 13000,   # 约 18:20（原版可睡窗口 12542 起，留缓冲）
        "night_end_tick": 23000,     # 约 05:45（23458 后躺下会立刻天亮，放弃）
        "return_after_sleep": True,  # 睡醒后返回睡觉前位置（false=留在睡觉点）
        "skip_when_busy": True,      # bot 有任务/战斗中时跳过，不打断任务
    }

    def __init__(self) -> None:
        self._context: Optional[PluginContext] = None
        self._enabled = True
        self._check_interval_s = 20
        self._night_start_tick = 13000
        self._night_end_tick = 23000
        self._return_after_sleep = True
        self._skip_when_busy = True
        self._tasks: dict[str, asyncio.Task] = {}
        # 每 bot 状态：睡觉前位置（回程用）与最近一次睡觉结果（状态接口展示）
        self._origin: dict[str, dict] = {}
        self._last_result: dict[str, dict] = {}

    # ── 生命周期 ──

    async def load(self, context: PluginContext) -> None:
        self._context = context

    def apply_config(self, config: dict) -> None:
        cfg = config or {}
        self._check_interval_s = max(5, int(cfg.get("check_interval_s", 20)))
        self._night_start_tick = max(0, min(24000, int(cfg.get("night_start_tick", 13000))))
        self._night_end_tick = max(0, min(24000, int(cfg.get("night_end_tick", 23000))))
        self._return_after_sleep = bool(cfg.get("return_after_sleep", True))
        self._skip_when_busy = bool(cfg.get("skip_when_busy", True))
        logger.info("auto_sleep config applied (interval={}s night={}-{} return={} skip_busy={})",
                    self._check_interval_s, self._night_start_tick, self._night_end_tick,
                    self._return_after_sleep, self._skip_when_busy)

    async def start(self) -> None:
        self._enabled = True
        logger.info("auto_sleep started")

    async def stop(self) -> None:
        self._enabled = False
        for task in self._tasks.values():
            task.cancel()
        self._tasks.clear()

    async def reload(self) -> None:
        await self.load(self._context)

    # ── 事件 ──

    async def on_event(self, event_type: str, payload: dict) -> None:
        if not self._enabled:
            return
        bot_id = payload.get("bot_id") or ""
        if not bot_id:
            return
        if event_type == "bot_spawned":
            self._ensure_loop(bot_id)
        elif event_type == "bot_disconnected":
            self._stop_loop(bot_id)

    # ── 轮询循环（bot_spawned 启动，bot_disconnected 停止） ──

    def _ensure_loop(self, bot_id: str) -> None:
        if bot_id in self._tasks and not self._tasks[bot_id].done():
            return
        self._tasks[bot_id] = asyncio.ensure_future(self._loop(bot_id))

    def _stop_loop(self, bot_id: str) -> None:
        task = self._tasks.pop(bot_id, None)
        if task and not task.done():
            task.cancel()

    async def _loop(self, bot_id: str) -> None:
        try:
            while self._enabled:
                try:
                    await self._tick(bot_id)
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    logger.warning("auto_sleep tick {} error: {}", bot_id, exc)
                await asyncio.sleep(self._check_interval_s)
        except asyncio.CancelledError:
            pass
        finally:
            self._tasks.pop(bot_id, None)
            self._origin.pop(bot_id, None)

    # ── 单轮决策 ──

    async def _tick(self, bot_id: str) -> None:
        if self._context is None:
            return
        client = self._context.pool.get_client(bot_id) if self._context else None
        if client is None or not client.is_connected:
            return

        # 1. 时间/状态
        try:
            st = await client.get_time_status()
        except Exception as exc:
            logger.debug("auto_sleep {} get_time_status failed: {}", bot_id, exc)
            return
        if not st.get("success"):
            return
        tod = st.get("time_of_day")
        if tod is None:
            return
        dim = st.get("dimension") or "unknown"
        is_sleeping = bool(st.get("is_sleeping"))

        # 2. 睡醒回程：天亮后（不在睡觉窗口）且记录过 origin → 返回睡觉前位置
        if not is_sleeping and self._return_after_sleep and bot_id in self._origin:
            origin = self._origin.pop(bot_id)
            if tod is not None and tod < self._night_start_tick:
                await self._go_back(bot_id, client, origin)
                return

        # 3. 已在睡 → 等天亮（服务器会自动唤醒）
        if is_sleeping:
            return

        # 4. 维度：仅主世界可睡觉
        if dim not in _OVERWORLD:
            self._record(bot_id, False, f"非主世界维度({dim})，跳过")
            return

        # 5. 服务器关闭昼夜循环 → 睡觉不会跳时间，记录并跳过
        if st.get("do_daylight_cycle") is False:
            self._record(bot_id, False, "服务器关闭昼夜循环(doDaylightCycle=false)，睡觉无效")
            return

        # 6. 时间窗口（或雷暴也可睡）
        in_window = self._night_start_tick <= tod <= self._night_end_tick
        thunderstorm = bool(st.get("is_raining")) and int(st.get("thunder_state") or 0) > 0
        if not in_window and not thunderstorm:
            return  # 白天/非雷暴：不需要睡觉

        # 7. 空闲判定（有任务/战斗中 → 本轮跳过，不打断）
        if self._skip_when_busy and await self._is_busy(bot_id, client):
            self._record(bot_id, False, "bot 忙碌（任务/战斗中），跳过睡觉")
            return

        # 8. 睡觉点
        sp = self._get_sleep_point(bot_id)
        if not sp:
            self._record(bot_id, False, "未配置睡觉点（功能 tab 中设置床的坐标）")
            return

        # 9. 执行睡觉
        origin = st.get("position")
        try:
            result = await client.sleep_at(x=sp["x"], y=sp["y"], z=sp["z"],
                                           timeout_ms=45000)
        except Exception as exc:
            self._record(bot_id, False, f"sleep_at 调用失败: {exc}")
            return
        ok = bool(result.get("success"))
        reason = result.get("reason") or ""
        self._record(bot_id, ok, reason)
        if ok and origin and self._return_after_sleep:
            self._origin[bot_id] = {"x": origin["x"], "y": origin["y"], "z": origin["z"]}
            logger.info("Bot {} sleeping at {} (origin {}), return_after_sleep enabled",
                        bot_id, sp, origin)

    # ── 睡醒回程 ──

    async def _go_back(self, bot_id: str, client, origin: dict) -> None:
        """天亮后寻路返回睡觉前位置（失败只记日志，不阻塞后续轮询）。"""
        try:
            from vmtools_next.adapters.mineflayer.mineflayer_client import MineflayerError
            r = await client.baritone_move(x=origin["x"], y=origin["y"], z=origin["z"],
                                           max_offset=2, timeout_ms=60000)
            if r.get("success"):
                logger.info("Bot {} returned to origin after sleep: {}", bot_id, origin)
                self._record(bot_id, True, "睡醒已返回原位置")
            else:
                logger.warning("Bot {} return-to-origin failed: {} (position {})",
                               bot_id, r.get("reason"), r.get("position"))
                self._record(bot_id, False, f"睡醒返回原位置失败: {r.get('reason')}")
        except Exception as exc:
            logger.warning("Bot {} return-to-origin error: {}", bot_id, exc)

    # ── 空闲判定（手动工作 > 物流 > 地图画 > 扫描 + 战斗） ──

    async def _is_busy(self, bot_id: str, client) -> bool:
        try:
            from vmtools_next.data.db import get_session_factory
            from vmtools_next.data.models.logistics import (
                MccBotModel, LogisticsTaskRunModel,
            )
            from vmtools_next.data.models.build_map_art import (
                MapArtBotAssignment, MapArtTask,
            )
            from vmtools_next.data.models.warehouse import ScanQueueModel
            db = get_session_factory()()
            try:
                # 手动标记「工作中」（优先级最高）
                bot_row = db.query(MccBotModel).filter(MccBotModel.bot_id == bot_id).first()
                if bot_row is not None and getattr(bot_row, "manual_working", False):
                    return True
                # 物流 running/paused
                run = db.query(LogisticsTaskRunModel).filter(
                    LogisticsTaskRunModel.bot_id == bot_id,
                    LogisticsTaskRunModel.status.in_(["running", "paused"]),
                ).first()
                if run is not None:
                    return True
                # 地图画 assignment（任务运行中）
                assign = db.query(MapArtBotAssignment).filter(
                    MapArtBotAssignment.bot_id == bot_id,
                ).all()
                task_ids = [a.task_id for a in assign if a.task_id]
                if task_ids:
                    running = db.query(MapArtTask).filter(
                        MapArtTask.task_id.in_(task_ids),
                        MapArtTask.status.in_(["running", "paused"]),
                    ).first()
                    if running is not None:
                        return True
                # 仓库扫描 pending/running/paused（排队中/进行中/暂停都算忙）
                scan = db.query(ScanQueueModel).filter(
                    ScanQueueModel.bot_id == bot_id,
                    ScanQueueModel.status.in_(["pending", "running", "paused"]),
                ).first()
                if scan is not None:
                    return True
            finally:
                db.close()
        except Exception as exc:
            logger.warning("auto_sleep {} busy check error: {}", bot_id, exc)
            return False  # 判定失败视为空闲，不阻塞睡觉（宁可睡也不卡死）
        # 战斗模式开启（auto-attack / guard）
        try:
            combat = await client.get_combat_status()
            if combat.get("success") and combat.get("active_mode"):
                return True
        except Exception:
            pass
        return False

    # ── 睡觉点读取（mcc_bots.sleep_x/y/z，per-bot） ──

    def _get_sleep_point(self, bot_id: str) -> Optional[dict]:
        try:
            from vmtools_next.data.db import get_session_factory
            from vmtools_next.data.models.logistics import MccBotModel
            db = get_session_factory()()
            try:
                row = db.query(MccBotModel).filter(MccBotModel.bot_id == bot_id).first()
                if row is None:
                    return None
                x, y, z = row.sleep_x, row.sleep_y, row.sleep_z
                if x is None or y is None or z is None:
                    return None
                return {"x": int(x), "y": int(y), "z": int(z)}
            finally:
                db.close()
        except Exception as exc:
            logger.warning("auto_sleep {} read sleep point error: {}", bot_id, exc)
            return None

    def _record(self, bot_id: str, ok: bool, reason: str) -> None:
        self._last_result[bot_id] = {
            "ok": ok,
            "reason": reason,
            "at": datetime.now(timezone.utc).isoformat(),
        }
        if ok:
            logger.info("auto_sleep {} 睡眠成功: {}", bot_id, reason)
        else:
            logger.info("auto_sleep {} 跳过/失败: {}", bot_id, reason)

    # ── 供状态接口读取（后端 sleep/status 直接 import 本类查缓存） ──

    def get_last_result(self, bot_id: str) -> Optional[dict]:
        return self._last_result.get(bot_id)
