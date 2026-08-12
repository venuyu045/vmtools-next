"""MfLogisticsRunner — Mineflayer 引擎物流执行器（2026-08-12，实施计划阶段 3）。

物流任务由 MCC（Baritone/TeleportManager）切换为 MF 实现：
完全复用 MineflayerBridgeClient 现有接口（寻路 move_to / 容器 open/read/withdraw/
deposit / 聊天 run_command 传送），流程与旧 LogisticsRunner 状态机语义对齐。

流程（对齐 LogisticsState）：
  TELEPORT_TO_SOURCE → NAVIGATE_TO_CONTAINER → OPEN_CONTAINER → READ_CONTAINER
  → WITHDRAW_ITEMS → TELEPORT_TO_DROP → NAVIGATE_TO_DROP → DEPOSIT_ITEMS
  （loop_mode == "loop" 时循环回源点；否则 COMPLETED）

进度：每次状态变化更新 LogisticsTaskRunModel（status/current_state/progress/
loop_count/error_message/finished_at）+ socket task_progress / task_queue_update。
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from vmtools_next.infra.logging import get_logger

logger = get_logger("mf_logistics")


class MfLogisticsRunner:
    """执行一次 MF 物流取送任务（单 run）。"""

    def __init__(
        self,
        run_id: str,
        bot_id: str,
        client,
        *,
        source_teleport_cmd: str = "",
        container_x: int = 0, container_y: int = 0, container_z: int = 0,
        item_type: str = "",
        item_count: int = 64,
        drop_teleport_cmd: str = "",
        drop_x: int = 0, drop_y: int = 0, drop_z: int = 0,
        drop_method: str = "drop",          # drop | container
        drop_container_xyz: tuple[int, int, int] | None = None,
        wait_after_teleport: int = 5,
        loop_mode: str = "once",            # once | loop
    ):
        self.run_id = run_id
        self.bot_id = bot_id
        self.client = client
        self._source_teleport_cmd = source_teleport_cmd
        self._container = (container_x, container_y, container_z)
        self._item_type = (item_type or "").split(":")[-1]  # 纯 id（prismarine-item name 无前缀）
        self._item_count = item_count
        self._drop_teleport_cmd = drop_teleport_cmd
        self._drop_pos = (drop_x, drop_y, drop_z)
        self._drop_method = drop_method
        self._drop_container = drop_container_xyz
        self._wait = wait_after_teleport
        self._loop_mode = loop_mode
        self._max_loops = 0 if loop_mode == "loop" else 1

        self._running = False
        self._paused = False
        self._stopped = False
        self._loop_count = 0
        self._current_state = "IDLE"
        self._error_message = ""
        self._task: asyncio.Task | None = None

    # ── 对外控制 ──

    async def start(self) -> None:
        if self._running or self._task:
            return
        self._running = True
        self._stopped = False
        self._paused = False
        self._loop_count = 0
        self._task = asyncio.create_task(self._execution_loop())

    async def stop(self) -> None:
        self._stopped = True
        self._paused = False
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def pause(self) -> None:
        self._paused = True
        await self._set_state("PAUSED", 0.0, "已暂停")

    async def resume(self) -> None:
        self._paused = False
        self._running = True

    # ── 状态推进 ──

    async def _set_state(self, state: str, progress: float, message: str = "") -> None:
        """更新 current_state + 落库 + socket 推送。"""
        self._current_state = state
        try:
            from vmtools_next.data.db import get_session_factory, sio
            Session = get_session_factory()
            db = Session()
            try:
                from vmtools_next.data.models.logistics import LogisticsTaskRunModel
                r = db.query(LogisticsTaskRunModel).filter(
                    LogisticsTaskRunModel.run_id == self.run_id).first()
                if r:
                    r.current_state = state
                    r.progress = round(progress, 4)
                    r.status = "running"
                    r.error_message = self._error_message or None
                    db.commit()
            finally:
                db.close()
            await sio.emit("task_progress", {
                "run_id": self.run_id,
                "bot_id": self.bot_id,
                "status": "running",
                "current_state": state,
                "progress": round(progress, 4),
                "loop_count": self._loop_count,
                "message": message,
            })
        except Exception as e:
            logger.warning("[{}] state persist failed: {}", self.run_id[:8], e)

    async def _complete(self, status: str, message: str = "") -> None:
        """任务结束（completed/failed/cancelled）：落库终态 + socket 广播。"""
        self._running = False
        self._current_state = "COMPLETED" if status == "completed" else self._current_state
        try:
            from vmtools_next.data.db import get_session_factory, sio
            Session = get_session_factory()
            db = Session()
            try:
                from vmtools_next.data.models.logistics import LogisticsTaskRunModel
                r = db.query(LogisticsTaskRunModel).filter(
                    LogisticsTaskRunModel.run_id == self.run_id).first()
                if r:
                    r.status = status
                    r.finished_at = datetime.now(timezone.utc)
                    r.error_message = message or self._error_message or None
                    db.commit()
            finally:
                db.close()
            await sio.emit("task_completed", {
                "run_id": self.run_id, "status": status, "message": message,
            })
            await sio.emit("task_queue_update", {
                "ts": datetime.now(timezone.utc).isoformat(),
            })
        except Exception as e:
            logger.warning("[{}] complete persist failed: {}", self.run_id[:8], e)

    # ── 主循环 ──

    async def _execution_loop(self) -> None:
        try:
            while self._running and not self._stopped:
                if self._paused:
                    await asyncio.sleep(0.5)
                    continue
                if self._loop_count > 0 and self._max_loops > 0 and self._loop_count >= self._max_loops:
                    break

                ok = await self._run_single_trip()
                if not ok:
                    break  # 失败已在内部标记
                self._loop_count += 1
                if self._loop_mode == "loop" and self._running and not self._stopped:
                    logger.info("[{}] loop {} complete, continuing...", self.run_id[:8], self._loop_count)
                    continue
                break

            if not self._stopped and self._current_state not in ("FAILED",):
                await self._complete("completed", f"完成 {self._loop_count} 趟")
        except asyncio.CancelledError:
            await self._complete("cancelled", "已停止")
        except Exception as e:
            self._error_message = str(e)
            logger.error("[{}] logistics loop error: {}", self.run_id[:8], e)
            await self._complete("failed", str(e))

    async def _run_single_trip(self) -> bool:
        """执行一趟取送：传送源点 → 取物 → 传送投放点 → 存入/丢弃。失败返回 False。"""
        c = self.client

        # 1. 传送源点
        await self._set_state("TELEPORT_TO_SOURCE", 0.1, "传送至源点...")
        if self._source_teleport_cmd:
            try:
                r = await c.run_command(self._source_teleport_cmd)
                if isinstance(r, dict) and r.get("success") is False:
                    raise RuntimeError(r.get("error", "传送命令失败"))
            except Exception as e:
                self._error_message = f"传送源点失败: {e}"
                await self._complete("failed", self._error_message)
                return False
            await asyncio.sleep(self._wait)

        # 2. 前往容器
        await self._set_state("NAVIGATE_TO_CONTAINER", 0.2, "前往源点容器...")
        if not await self._move_to(c, *self._container, label="源点容器"):
            return False

        # 3. 打开容器
        await self._set_state("OPEN_CONTAINER", 0.3, "打开源点容器...")
        container_id = None
        try:
            open_res = await c.open_container_at(*self._container, timeout_ms=8000)
            if isinstance(open_res, dict) and not open_res.get("success"):
                raise RuntimeError(open_res.get("error", "打开容器失败"))
            container_id = (open_res or {}).get("container_id")
        except Exception as e:
            self._error_message = f"打开容器失败: {e}"
            await self._complete("failed", self._error_message)
            return False

        # 4. 读取容器（确认物品存在）
        await self._set_state("READ_CONTAINER", 0.4, "读取容器内容...")
        try:
            snap = await c.get_container_snapshot(container_id)
            items = (snap or {}).get("items") or []
            found = any(
                (i.get("name") or "").split(":")[-1] == self._item_type and (i.get("count") or 0) > 0
                for i in items
            )
        except Exception:
            found = True  # 读取失败不阻断（withdraw 会再校验）
        if not found:
            self._error_message = f"源点容器中没有 {self._item_type}"
            await c.close_container(container_id)
            await self._complete("failed", self._error_message)
            return False

        # 5. 取物品
        await self._set_state("WITHDRAW_ITEMS", 0.5, f"取 {self._item_type} ×{self._item_count}...")
        try:
            wr = await c.withdraw_container_item(self._item_type, self._item_count, container_id)
            if isinstance(wr, dict) and not wr.get("success"):
                raise RuntimeError(wr.get("error", "取物品失败"))
            await c.close_container(container_id)
        except Exception as e:
            self._error_message = f"取物品失败: {e}"
            await self._complete("failed", self._error_message)
            return False

        # 6. 传送投放点
        await self._set_state("TELEPORT_TO_DROP", 0.6, "传送至投放点...")
        if self._drop_teleport_cmd:
            try:
                r = await c.run_command(self._drop_teleport_cmd)
                if isinstance(r, dict) and r.get("success") is False:
                    raise RuntimeError(r.get("error", "传送命令失败"))
            except Exception as e:
                self._error_message = f"传送投放点失败: {e}"
                await self._complete("failed", self._error_message)
                return False
            await asyncio.sleep(self._wait)

        # 7. 前往投放点（container 方式需到容器旁；drop 方式到投放坐标）
        target = self._drop_container or self._drop_pos
        await self._set_state("NAVIGATE_TO_DROP", 0.7, "前往投放点...")
        if not await self._move_to(c, *target, label="投放点"):
            return False

        # 8. 存入/丢弃
        await self._set_state("DEPOSIT_ITEMS", 0.8, "投放物品...")
        try:
            if self._drop_method == "container" and self._drop_container:
                open_res = await c.open_container_at(*self._drop_container, timeout_ms=8000)
                if not (isinstance(open_res, dict) and open_res.get("success")):
                    raise RuntimeError((open_res or {}).get("error", "打开投放容器失败"))
                did = (open_res or {}).get("container_id")
                await c.deposit_container_item(self._item_type, self._item_count, did)
                await c.close_container(did)
            else:
                await c.drop_inventory_item(self._item_type, self._item_count)
        except Exception as e:
            self._error_message = f"投放失败: {e}"
            await self._complete("failed", self._error_message)
            return False

        await self._set_state("COMPLETED", 1.0, "本趟完成")
        return True

    async def _move_to(self, c, x: int, y: int, z: int, label: str = "") -> bool:
        """寻路（15s 超时，失败重试 1 次）。"""
        for attempt in range(2):
            if self._stopped:
                return False
            try:
                r = await c.move_to(x, y, z, max_offset=2, timeout_ms=15000)
                if isinstance(r, dict) and r.get("success"):
                    return True
                logger.warning("[{}] move_to {} (attempt {}/2) failed: {}",
                               self.run_id[:8], label or (x, y, z), attempt + 1, r)
            except Exception as e:
                logger.warning("[{}] move_to {} error: {}", self.run_id[:8], label or (x, y, z), e)
            await asyncio.sleep(1.0)
        self._error_message = f"寻路失败: {label}"
        await self._complete("failed", self._error_message)
        return False