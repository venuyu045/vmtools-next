"""定时任务调度器 + 任务记录保留清理（2026-08-13 任务管理页）。

- 每分钟 tick：匹配到期的定时任务（once/daily/weekly）并执行：
    * scan   → ScanQueueManager.enqueue（仓库扫描入队）
    * logistics → 创建 pending 物流 run（模板+bot）→ 由 TaskScheduler 自动启动
    * map_art → 启动已创建的 pending/paused 地图画任务
  执行前校验 bot 手动标记「工作中」→ 自动跳过（ensure_available_for_work）。
- 每日清理：删除终态（completed/failed/cancelled）且结束时间距今 >7 天的
  扫描/地图画/物流记录（含关联日志），控制任务中心数据量。
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone

from vmtools_next.data.db import get_session_factory, sio
from vmtools_next.infra.logging import get_logger

logger = get_logger("scheduled_task_scheduler")

_RETENTION_DAYS = 7
_TERMINAL_STATUS = ("completed", "failed", "cancelled")


class ScheduledTaskScheduler:
    def __init__(self, poll_interval: float = 60.0):
        self._poll_interval = poll_interval
        self._scheduler_task: asyncio.Task | None = None
        self._running = False
        self._last_cleanup_day: str | None = None

    # ── 生命周期 ──

    async def start(self) -> None:
        self._running = True
        self._scheduler_task = asyncio.create_task(self._loop())
        logger.info("ScheduledTaskScheduler started (poll={}s, retention={}d)",
                    self._poll_interval, _RETENTION_DAYS)

    async def stop(self) -> None:
        self._running = False
        if self._scheduler_task:
            self._scheduler_task.cancel()
            try:
                await self._scheduler_task
            except asyncio.CancelledError:
                pass
            self._scheduler_task = None
        logger.info("ScheduledTaskScheduler stopped")

    # ── 主循环 ──

    async def _loop(self) -> None:
        while self._running:
            try:
                await self.tick_once()
            except Exception as e:
                logger.warning("Scheduled task tick error: {}", e)
            # 每日清理（按 UTC 日期切换执行一次）
            today = datetime.now(timezone.utc).date().isoformat()
            if today != self._last_cleanup_day:
                try:
                    await self.cleanup_old_records()
                    self._last_cleanup_day = today
                except Exception as e:
                    logger.warning("Retention cleanup error: {}", e)
            await asyncio.sleep(self._poll_interval)

    async def tick_once(self) -> None:
        """检查并执行所有到期的定时任务。"""
        from vmtools_next.data.models.scheduled_task import ScheduledTaskModel

        Session = get_session_factory()
        db = Session()
        try:
            due = db.query(ScheduledTaskModel).filter(
                ScheduledTaskModel.enabled.is_(True),
            ).all()
        finally:
            db.close()

        fired_any = False
        now = datetime.now(timezone.utc)
        for task in due:
            if not self._is_due(task, now):
                continue
            fired_any = True
            await self._execute(task)
        if fired_any:
            await self._broadcast()

    @staticmethod
    def _is_due(task, now: datetime) -> bool:
        kind = task.schedule_kind
        if kind == "once":
            if not task.run_at:
                return False
            # SQLite 存储为 naive datetime；now 为 aware → 统一转 naive UTC 比较
            now_naive = now.replace(tzinfo=None) if now.tzinfo is not None else now
            run_at_naive = task.run_at.replace(tzinfo=None) if task.run_at.tzinfo is not None else task.run_at
            return now_naive >= run_at_naive
        if kind == "daily":
            return now.strftime("%H:%M") == (task.schedule_time or "")
        if kind == "weekly":
            return (now.weekday() == (task.schedule_weekday or 0)
                    and now.strftime("%H:%M") == (task.schedule_time or ""))
        return False

    # ── 执行 ──

    async def _execute(self, task) -> None:
        """执行单个定时任务（对每个 bot 逐个发起）。执行后更新 last_run_at，once 自动停用。"""
        import uuid as _uuid
        from vmtools_next.core.bot_work import ensure_available_for_work

        Session = get_session_factory()
        db = Session()
        try:
            task = db.merge(task)  # 重新绑定到本 session
            bot_ids = json.loads(task.bot_ids or "[]")
            results: list[str] = []

            if task.task_type == "scan":
                from vmtools_next.main import get_scan_queue_manager
                mgr = get_scan_queue_manager()
                for bid in bot_ids:
                    err = ensure_available_for_work(db, bid, "定时任务·仓库扫描")
                    if err:
                        results.append(f"{bid}: 跳过（{err}）")
                        continue
                    if mgr is None:
                        results.append(f"{bid}: 扫描管理器未就绪")
                        continue
                    r = await mgr.enqueue(task.target_id, bid)
                    results.append(f"{bid}: {'已入队' if r.get('ok') else (r.get('error') or '失败')}")

            elif task.task_type == "logistics":
                from vmtools_next.data.models.logistics import (
                    LogisticsTaskRunModel, LogisticsTaskTemplateModel,
                )
                from vmtools_next.core.bot_engine import resolve_bot_engine

                tpl = db.query(LogisticsTaskTemplateModel).filter(
                    LogisticsTaskTemplateModel.template_id == task.target_id).first()
                if not tpl or not tpl.enabled:
                    results.append("模板不存在或已停用")
                else:
                    for bid in bot_ids:
                        err = ensure_available_for_work(db, bid, "定时任务·物流")
                        if err:
                            results.append(f"{bid}: 跳过（{err}）")
                            continue
                        if resolve_bot_engine(bid, db) != "mineflayer":
                            results.append(f"{bid}: 非 MF 引擎，跳过")
                            continue
                        active = db.query(LogisticsTaskRunModel).filter(
                            LogisticsTaskRunModel.bot_id == bid,
                            LogisticsTaskRunModel.status.in_(["pending", "running", "paused"]),
                        ).first()
                        if active:
                            results.append(f"{bid}: 已有进行中的物流任务，跳过")
                            continue
                        run = LogisticsTaskRunModel(
                            run_id=_uuid.uuid4().hex,
                            template_id=task.target_id,
                            bot_id=bid,
                            status="pending",
                            current_state="IDLE",
                            progress=0.0,
                        )
                        db.add(run)
                        results.append(f"{bid}: 已入队")
                    db.commit()
                    try:
                        from vmtools_next.core.task_scheduler import get_task_scheduler
                        sched = get_task_scheduler()
                        if sched:
                            asyncio.create_task(sched.schedule_once())
                    except Exception as e:
                        logger.warning("Scheduled logistics trigger failed: {}", e)

            elif task.task_type == "map_art":
                from vmtools_next.data.models.build_map_art import MapArtTask
                from vmtools_next.api.routers.build_map_art import execute_map_art_start

                art = db.query(MapArtTask).filter(
                    MapArtTask.task_id == task.target_id).first()
                if not art:
                    results.append("地图画任务不存在")
                elif art.status == "running":
                    results.append("任务已在运行，跳过")
                elif art.status in _TERMINAL_STATUS:
                    results.append(f"任务已结束（{art.status}），跳过")
                elif art.status in ("pending", "paused"):
                    art.status = "running"
                    art.started_at = datetime.now(timezone.utc)
                    db.commit()
                    ok, msg = await execute_map_art_start(task.target_id, db)
                    results.append("已启动" if ok else f"启动失败: {msg}")
                    if not ok:
                        art = db.query(MapArtTask).filter(
                            MapArtTask.task_id == task.target_id).first()
                        if art:
                            art.status = "failed"
                            art.error_message = msg
                            art.completed_at = datetime.now(timezone.utc)
                            db.commit()
                else:
                    results.append(f"任务状态 {art.status}，跳过")

            now = datetime.now(timezone.utc)
            task.last_run_at = now
            if task.schedule_kind == "once":
                task.enabled = False  # 一次性任务执行后自动停用
            db.commit()
            logger.info("Scheduled task {} ({}) fired: {}", task.id[:8], task.name, " | ".join(results))
        except Exception as e:
            logger.warning("Scheduled task {} execute error: {}", getattr(task, "id", "?"), e)
        finally:
            db.close()

    # ── 7 天记录清理 ──

    async def cleanup_old_records(self) -> None:
        """删除终态且结束时间 >7 天的扫描/地图画/物流记录（含关联日志）。"""
        from vmtools_next.data.models.warehouse import ScanQueueModel
        from vmtools_next.data.models.build_map_art import (
            MapArtTask, MapArtMaterial, MapArtBotAssignment, MapArtBlockState,
        )
        from vmtools_next.data.models.logistics import (
            LogisticsTaskRunModel, LogisticsTaskLogModel,
        )

        Session = get_session_factory()
        db = Session()
        try:
            cutoff = datetime.now(timezone.utc) - timedelta(days=_RETENTION_DAYS)

            # 1) 仓库扫描
            del_scan = db.query(ScanQueueModel).filter(
                ScanQueueModel.status.in_(_TERMINAL_STATUS),
                ScanQueueModel.finished_at.isnot(None),
                ScanQueueModel.finished_at < cutoff,
            ).all()
            n_scan = len(del_scan)
            for r in del_scan:
                db.delete(r)
            db.flush()

            # 2) 地图画（含关联表）
            del_arts = db.query(MapArtTask).filter(
                MapArtTask.status.in_(_TERMINAL_STATUS),
                MapArtTask.completed_at.isnot(None),
                MapArtTask.completed_at < cutoff,
            ).all()
            n_art = len(del_arts)
            if del_arts:
                art_ids = [a.task_id for a in del_arts]
                db.query(MapArtBlockState).filter(
                    MapArtBlockState.task_id.in_(art_ids)).delete(synchronize_session=False)
                db.query(MapArtBotAssignment).filter(
                    MapArtBotAssignment.task_id.in_(art_ids)).delete(synchronize_session=False)
                db.query(MapArtMaterial).filter(
                    MapArtMaterial.task_id.in_(art_ids)).delete(synchronize_session=False)
                for a in del_arts:
                    db.delete(a)
                db.flush()

            # 3) 物流（含日志）
            del_runs = db.query(LogisticsTaskRunModel).filter(
                LogisticsTaskRunModel.status.in_(_TERMINAL_STATUS),
                LogisticsTaskRunModel.finished_at.isnot(None),
                LogisticsTaskRunModel.finished_at < cutoff,
            ).all()
            n_run = len(del_runs)
            if del_runs:
                run_ids = [r.run_id for r in del_runs]
                db.query(LogisticsTaskLogModel).filter(
                    LogisticsTaskLogModel.run_id.in_(run_ids)).delete(synchronize_session=False)
                for r in del_runs:
                    db.delete(r)
                db.flush()

            db.commit()
            if n_scan or n_art or n_run:
                logger.info("Retention cleanup: removed {} scans, {} map_arts, {} logistics (>{}d)",
                            n_scan, n_art, n_run, _RETENTION_DAYS)
        except Exception as e:
            logger.warning("Retention cleanup error: {}", e)
            db.rollback()
        finally:
            db.close()

    # ── 广播 ──

    async def _broadcast(self) -> None:
        try:
            await sio.emit("task_queue_update", {
                "ts": datetime.now(timezone.utc).isoformat(),
            })
        except Exception as e:
            logger.debug("task_queue_update emit skipped: {}", e)


# 全局单例（main.py lifespan 初始化）
_scheduled_task_scheduler: ScheduledTaskScheduler | None = None


def get_scheduled_task_scheduler() -> ScheduledTaskScheduler | None:
    return _scheduled_task_scheduler


def set_scheduled_task_scheduler(scheduler: ScheduledTaskScheduler) -> None:
    global _scheduled_task_scheduler
    _scheduled_task_scheduler = scheduler
