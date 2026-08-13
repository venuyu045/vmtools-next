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

    def __init__(self, max_concurrent_build: int = 1, poll_interval: float = 2.0,
                 max_concurrent_logistics: int = 1):
        self._max_concurrent_build = max_concurrent_build
        self._max_concurrent_logistics = max_concurrent_logistics
        self._poll_interval = poll_interval
        self._scheduler_task: asyncio.Task | None = None
        self._running = False
        self._logistics_runners: dict[str, object] = {}  # run_id -> MfLogisticsRunner

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
        """启动排队中的地图画/物流任务，直到达到各自并发上限。"""
        # ── 地图画调度 ──
        map_art_candidates = await self._pick_map_art_candidates()
        for task_id in map_art_candidates:
            await self._start_map_art(task_id)

        # ── 物流调度 ──
        logistics_candidates = await self._pick_logistics_candidates()
        for run_id in logistics_candidates:
            await self._start_logistics(run_id)

    # ── 地图画 ──

    async def _pick_map_art_candidates(self) -> list[str]:
        """取最早 pending 地图画任务（立即置 running 防竞态）。"""
        from vmtools_next.data.models.build_map_art import MapArtTask

        Session = get_session_factory()
        db = Session()
        candidates: list[str] = []
        try:
            running = db.query(MapArtTask).filter(
                MapArtTask.status == "running",
            ).count()
            if running >= self._max_concurrent_build:
                return candidates
            slot = self._max_concurrent_build - running
            pending = db.query(MapArtTask).filter(
                MapArtTask.status == "pending",
            ).order_by(
                MapArtTask.created_at.asc(),
            ).limit(slot).all()
            for t in pending:
                t.status = "running"
                t.started_at = datetime.now(timezone.utc)
                db.commit()
                candidates.append(t.task_id)
        finally:
            db.close()
        return candidates

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

    # ── 物流（MF，2026-08-12 阶段 3） ──

    async def _pick_logistics_candidates(self) -> list[str]:
        """取最早 pending 物流 run（立即置 running 防竞态；跳过 bot 被占用的）。"""
        from vmtools_next.data.models.logistics import LogisticsTaskRunModel

        Session = get_session_factory()
        db = Session()
        candidates: list[str] = []
        try:
            running = len(self._logistics_runners)
            if running >= self._max_concurrent_logistics:
                return candidates
            slot = self._max_concurrent_logistics - running
            pending = db.query(LogisticsTaskRunModel).filter(
                LogisticsTaskRunModel.status == "pending",
            ).order_by(
                LogisticsTaskRunModel.started_at.asc(),
            ).limit(slot * 3).all()  # 多取几个，过滤掉 bot 被占用的
            for r in pending:
                if len(candidates) >= slot:
                    break
                if self._bot_busy(r.bot_id, db):
                    continue
                r.status = "running"
                db.commit()
                candidates.append(r.run_id)
        finally:
            db.close()
        return candidates

    def _bot_busy(self, bot_id: str, db) -> bool:
        """该 bot 是否已在运行中的地图画任务（assignment）、物流任务中，或手动标记「工作中」。"""
        try:
            # 手动标记「工作中」（2026-08-13 任务管理）：调度器不派活
            from vmtools_next.core.bot_work import get_manual_work
            if get_manual_work(db, bot_id) is not None:
                return True
            from vmtools_next.data.models.build_map_art import MapArtTask, MapArtBotAssignment
            from vmtools_next.data.models.logistics import LogisticsTaskRunModel
            running_tasks = db.query(MapArtTask.task_id).filter(
                MapArtTask.status == "running").all()
            if running_tasks:
                tids = [t[0] for t in running_tasks]
                if tids:
                    hit = db.query(MapArtBotAssignment).filter(
                        MapArtBotAssignment.task_id.in_(tids),
                        MapArtBotAssignment.bot_id == bot_id,
                    ).first()
                    if hit:
                        return True
            hit2 = db.query(LogisticsTaskRunModel).filter(
                LogisticsTaskRunModel.bot_id == bot_id,
                LogisticsTaskRunModel.status.in_(["running", "paused"]),
            ).first()
            return hit2 is not None
        except Exception:
            return False

    async def _start_logistics(self, run_id: str) -> None:
        """启动单个 MF 物流任务；失败置 failed 并继续调度下一个。"""
        from vmtools_next.data.models.logistics import (
            LogisticsTaskRunModel, LogisticsTaskTemplateModel,
            LogisticsWaypointModel, LogisticsDropPointModel,
        )
        from vmtools_next.core.mf_logistics_runner import MfLogisticsRunner
        from vmtools_next.main import get_pool_for_engine

        Session = get_session_factory()
        db = Session()
        try:
            run = db.query(LogisticsTaskRunModel).filter(
                LogisticsTaskRunModel.run_id == run_id).first()
            if not run:
                return
            tpl = db.query(LogisticsTaskTemplateModel).filter(
                LogisticsTaskTemplateModel.template_id == run.template_id).first()
            wp = db.query(LogisticsWaypointModel).filter(
                LogisticsWaypointModel.waypoint_id == (tpl.source_waypoint_id if tpl else None)).first()
            dp = db.query(LogisticsDropPointModel).filter(
                LogisticsDropPointModel.drop_point_id == (tpl.drop_point_id if tpl else None)).first()

            pool = get_pool_for_engine("mineflayer")
            client = pool.get_client(run.bot_id) if pool else None
            if not client:
                run.status = "failed"
                run.error_message = "Bot 未连接，无法启动物流任务"
                run.finished_at = datetime.now(timezone.utc)
                db.commit()
                logger.warning("Logistics run {} failed: bot {} not connected",
                               run_id[:8], run.bot_id)
                return

            runner = MfLogisticsRunner(
                run_id=run_id,
                bot_id=run.bot_id,
                client=client,
                source_teleport_cmd=(wp.teleport_command if wp else ""),
                container_x=(wp.container_x if wp else 0),
                container_y=(wp.container_y if wp else 0),
                container_z=(wp.container_z if wp else 0),
                item_type=(wp.item_id if wp and wp.item_id else (wp.item_name if wp else "")),
                item_count=64,
                drop_teleport_cmd=(dp.teleport_command if dp else ""),
                drop_x=(dp.drop_x or 0) if dp else 0,
                drop_y=(dp.drop_y or 0) if dp else 0,
                drop_z=(dp.drop_z or 0) if dp else 0,
                drop_method=(dp.drop_method if dp else "drop"),
                drop_container_xyz=(
                    (dp.container_x, dp.container_y, dp.container_z)
                    if dp and dp.drop_method == "container" and dp.container_x is not None else None
                ),
                wait_after_teleport=(wp.wait_after_teleport if wp and wp.wait_after_teleport else 5),
                loop_mode=(tpl.loop_mode if tpl else "once"),
            )
            self._logistics_runners[run_id] = runner
        finally:
            db.close()

        await runner.start()
        # 等待执行完成（watch 模式，完成后清理并继续调度）
        try:
            await runner._task
        except asyncio.CancelledError:
            pass
        finally:
            self._logistics_runners.pop(run_id, None)
            await self.broadcast_queue()
            await self.schedule_once()

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
