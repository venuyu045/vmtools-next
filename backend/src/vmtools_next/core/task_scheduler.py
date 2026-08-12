"""Task Scheduler — 统一任务调度器（2026-08-12，实施计划阶段 2）。

设计（参考 scan_queue_manager 的 DB 队列 + 调度循环模式）：
- 地图画任务：`MapArtTask.status == "pending"` = 排队中；`"running"` = 执行中；
  并发上限 `task_max_concurrent_build`（默认 1）；running 完成后自动启动最早 pending。
- 防竞态：调度器取出 pending 后**立即置 running 落库**再执行启动（避免轮询间隔内
  下一轮重复选中同一任务）。
- 孤儿清理：后端重启/崩溃残留的 running（coordinator 已不在内存）→ 置 failed。
- 实时广播：任务状态变化统一 emit `task_queue_update`（任务中心实时刷新）。
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from vmtools_next.data.db import get_session_factory, sio
from vmtools_next.infra.logging import get_logger

logger = get_logger("task_scheduler")


class TaskScheduler:
    """Manages the auto-scheduling queue for build / logistics tasks."""

    def __init__(self, max_concurrent_build: int = 1, poll_interval: float = 2.0):
        self._max_concurrent_build = max_concurrent_build
        self._poll_interval = poll_interval
        self._scheduler_task: asyncio.Task | None = None
        self._running = False

    # ── 生命周期 ──

    async def start(self) -> None:
        self._running = True
        # 孤儿清理：后端重启后内存 coordinator 已不存在，残留 running 任务无法恢复 → failed
        try:
            from vmtools_next.data.models.build_map_art import MapArtTask
            Session = get_session_factory()
            db = Session()
            try:
                orphans = db.query(MapArtTask).filter(
                    MapArtTask.status == "running",
                ).all()
                if orphans:
                    now = datetime.now(timezone.utc)
                    for t in orphans:
                        t.status = "failed"
                        t.error_message = "后端重启，任务中断（调度器孤儿清理）"
                        t.completed_at = now
                    db.commit()
                    logger.info("TaskScheduler cleaned {} orphan running tasks", len(orphans))
            finally:
                db.close()
        except Exception as e:
            logger.warning("Orphan task cleanup failed: {}", e)

        self._scheduler_task = asyncio.create_task(self._scheduler_loop())
        logger.info("TaskScheduler started (max_concurrent_build={})", self._max_concurrent_build)

    async def stop(self) -> None:
        self._running = False
        if self._scheduler_task:
            self._scheduler_task.cancel()
            try:
                await self._scheduler_task
            except asyncio.CancelledError:
                pass
            self._scheduler_task = None
        logger.info("TaskScheduler stopped")

    # ── 调度循环 ──

    async def _scheduler_loop(self) -> None:
        while self._running:
            try:
                await self.schedule_once()
            except Exception as e:
                logger.warning("Task scheduler error: {}", e)
            await asyncio.sleep(self._poll_interval)

    async def schedule_once(self) -> None:
        """启动排队中的地图画任务，直到达到并发上限。"""
        from vmtools_next.data.models.build_map_art import MapArtTask
        from vmtools_next.api.routers.build_map_art import execute_map_art_start

        Session = get_session_factory()
        db = Session()
        candidates: list[str] = []
        try:
            running = db.query(MapArtTask).filter(
                MapArtTask.status == "running",
            ).count()
            if running >= self._max_concurrent_build:
                return
            slot = self._max_concurrent_build - running
            pending = db.query(MapArtTask).filter(
                MapArtTask.status == "pending",
            ).order_by(
                MapArtTask.created_at.asc(),
            ).limit(slot).all()
            # 立即置 running（防调度器下一轮重复选中），随后在新 session 内执行启动
            for t in pending:
                t.status = "running"
                t.started_at = datetime.now(timezone.utc)
                db.commit()
                candidates.append(t.task_id)
        finally:
            db.close()

        for task_id in candidates:
            await self._start_map_art(task_id)

    async def _start_map_art(self, task_id: str) -> None:
        """启动单个地图画任务；失败置 failed 并继续调度下一个。"""
        from vmtools_next.data.models.build_map_art import MapArtTask
        from vmtools_next.api.routers.build_map_art import execute_map_art_start

        Session = get_session_factory()
        db = Session()
        try:
            ok, msg = await execute_map_art_start(task_id, db)
            if not ok:
                t = db.query(MapArtTask).filter(MapArtTask.task_id == task_id).first()
                if t:
                    t.status = "failed"
                    t.error_message = msg
                    t.completed_at = datetime.now(timezone.utc)
                    db.commit()
                    logger.warning("Task {} auto-start failed: {}", task_id, msg)
        finally:
            db.close()

        await self.broadcast_queue()
        # 失败后立即尝试启动下一个排队任务（若本任务成功，running 已占满无需再取）
        await self.schedule_once()

    # ── 广播 ──

    async def broadcast_queue(self) -> None:
        """广播任务队列变化（任务中心 /tasks 实时刷新）。"""
        try:
            await sio.emit("task_queue_update", {
                "ts": datetime.now(timezone.utc).isoformat(),
            })
        except Exception as e:
            logger.debug("task_queue_update emit skipped: {}", e)


# 全局单例（main.py lifespan 初始化）
_task_scheduler: TaskScheduler | None = None


def get_task_scheduler() -> TaskScheduler | None:
    """返回全局任务调度器（未初始化时为 None）。"""
    return _task_scheduler


def set_task_scheduler(scheduler: TaskScheduler) -> None:
    global _task_scheduler
    _task_scheduler = scheduler
