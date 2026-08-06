"""Scan Queue Manager — 多仓库扫描队列与资源调度。

设计目标（面向几千万物品的大仓库）：
- 多仓库排队：一个时间点同时最多 ``max_concurrent_scans`` 个扫描在跑，
  其余 pending 排队，前面的完成后自动启动下一个。
- 资源分配：同一 bot 同一时间只跑一个扫描；每个扫描内部仍用
  WarehouseScanner 的 Semaphore(16) 并发读容器（NBT backpressure）。
- 实时进度：scan_progress 事件带 scanned/total/items/speed/eta，
  scan_status 落库 items_scanned。
- 崩溃不丢：扫描完成/取消时落库；结果分批 flush，避免超大事务。
"""
from __future__ import annotations

import asyncio
import logging
import time
import uuid
from datetime import datetime, timezone

from vmtools_next.data.db import get_session_factory, sio
from vmtools_next.infra.logging import get_logger

logger = get_logger("scan_queue")

# mineflayer scan_nearby_blocks 匹配的容器方块（逗号分隔）
_CONTAINER_MATCHING = (
    "chest,trapped_chest,barrel,hopper,dispenser,dropper,furnace,blast_furnace,"
    "smoker,brewing_stand,ender_chest,shulker_box,white_shulker_box,orange_shulker_box,"
    "magenta_shulker_box,light_blue_shulker_box,yellow_shulker_box,lime_shulker_box,"
    "pink_shulker_box,gray_shulker_box,light_gray_shulker_box,cyan_shulker_box,"
    "purple_shulker_box,blue_shulker_box,brown_shulker_box,green_shulker_box,red_shulker_box,black_shulker_box"
)


class ScanQueueManager:
    """Manages a persistent scan queue (DB-backed) with a scheduler loop."""

    def __init__(self, max_concurrent_scans: int = 2, poll_interval: float = 2.0):
        self._max_concurrent = max_concurrent_scans
        self._poll_interval = poll_interval
        self._scanners: dict[str, object] = {}   # queue_id -> WarehouseScanner
        self._started_at: dict[str, float] = {}  # queue_id -> wall time
        self._scheduler_task: asyncio.Task | None = None
        self._running = False

    # ── 生命周期 ──
    async def start(self) -> None:
        self._running = True
        self._scheduler_task = asyncio.create_task(self._scheduler_loop())
        logger.info("ScanQueueManager started (max_concurrent=%d)", self._max_concurrent)

    async def stop(self) -> None:
        self._running = False
        if self._scheduler_task:
            self._scheduler_task.cancel()
            try:
                await self._scheduler_task
            except asyncio.CancelledError:
                pass
            self._scheduler_task = None
        logger.info("ScanQueueManager stopped")

    # ── 对外接口 ──
    async def enqueue(self, warehouse_id: str, bot_id: str, priority: int = 0) -> dict:
        """入队一个仓库扫描。校验重复/资源占用后创建 pending 记录。"""
        from vmtools_next.data.models.warehouse import ScanQueueModel, WarehouseModel

        Session = get_session_factory()
        db = Session()
        queue_id = None
        try:
            wh = db.query(WarehouseModel).filter(
                WarehouseModel.warehouse_id == warehouse_id).first()
            if not wh:
                return {"ok": False, "error": "Warehouse not found"}

            active = db.query(ScanQueueModel).filter(
                ScanQueueModel.status.in_(["pending", "running", "paused"])
            ).all()
            for q in active:
                if q.warehouse_id == warehouse_id:
                    return {"ok": False, "error": "该仓库已有扫描任务在排队/进行中"}
                if q.bot_id == bot_id and q.status in ("running", "paused"):
                    return {"ok": False, "error": f"Bot {bot_id} 已有进行中的扫描任务"}

            q = ScanQueueModel(
                queue_id=str(uuid.uuid4()),
                warehouse_id=warehouse_id,
                bot_id=bot_id,
                priority=priority,
                status="pending",
            )
            db.add(q)
            db.commit()
            db.refresh(q)
            queue_id = q.queue_id
            # scan_status 标记 queued
            try:
                from vmtools_next.core.warehouse_scan_service import mark_scan_queued
                mark_scan_queued(db, warehouse_id)
            except Exception:
                pass
        finally:
            db.close()

        await self._broadcast_queue()
        await self._schedule_once()
        return {"ok": True, "queue_id": queue_id}

    async def control(self, queue_id: str, action: str) -> dict:
        """对队列项执行 pause / resume / cancel。"""
        from vmtools_next.data.models.warehouse import ScanQueueModel, ScanStatusModel

        Session = get_session_factory()
        db = Session()
        try:
            q = db.query(ScanQueueModel).filter(
                ScanQueueModel.queue_id == queue_id).first()
            if not q:
                return {"ok": False, "error": "Scan queue item not found"}
            scanner = self._scanners.get(queue_id)

            if action == "pause":
                if q.status == "running" and scanner is not None:
                    await scanner.pause()
                    q.status = "paused"
                    db.commit()
                elif q.status == "pending":
                    q.status = "paused"
                    db.commit()
                else:
                    return {"ok": False, "error": "任务不在可暂停状态"}
            elif action == "resume":
                if q.status == "paused":
                    if scanner is not None:
                        await scanner.resume()
                        q.status = "running"
                    else:
                        q.status = "pending"
                    db.commit()
                    await self._schedule_once()
                else:
                    return {"ok": False, "error": "任务不在暂停状态"}
            elif action == "cancel":
                if scanner is not None:
                    await scanner.cancel()
                q.status = "cancelled"
                q.finished_at = datetime.now(timezone.utc)
                db.commit()
                self._scanners.pop(queue_id, None)
                self._started_at.pop(queue_id, None)
                try:
                    st = db.query(ScanStatusModel).filter(
                        ScanStatusModel.warehouse_fk == q.warehouse_id).first()
                    if st:
                        st.status = "cancelled"
                        st.finished_at = datetime.now(timezone.utc)
                        db.commit()
                except Exception:
                    pass
            else:
                return {"ok": False, "error": f"Unknown action: {action}"}
        finally:
            db.close()

        await self._broadcast_queue()
        await self._schedule_once()
        return {"ok": True}

    async def list_queue(self) -> list[dict]:
        """返回队列列表（含近期历史）。"""
        from vmtools_next.data.models.warehouse import ScanQueueModel

        Session = get_session_factory()
        db = Session()
        try:
            rows = db.query(ScanQueueModel).order_by(
                ScanQueueModel.created_at.desc(),
            ).limit(50).all()
            return [self._serialize(q) for q in rows]
        finally:
            db.close()

    @staticmethod
    def _serialize(q) -> dict:
        return {
            "queue_id": q.queue_id,
            "warehouse_id": q.warehouse_id,
            "bot_id": q.bot_id,
            "priority": q.priority,
            "status": q.status,
            "error": q.error,
            "total_containers": q.total_containers or 0,
            "scanned_containers": q.scanned_containers or 0,
            "items_scanned": q.items_scanned or 0,
            "failed_containers": q.failed_containers or 0,
            "progress": q.progress or 0.0,
            "created_at": q.created_at.isoformat() if q.created_at else None,
            "started_at": q.started_at.isoformat() if q.started_at else None,
            "finished_at": q.finished_at.isoformat() if q.finished_at else None,
        }

    # ── 调度 ──
    async def _scheduler_loop(self) -> None:
        while self._running:
            try:
                await self._schedule_once()
            except Exception as e:
                logger.warning("Scan scheduler error: %s", e)
            await asyncio.sleep(self._poll_interval)

    async def _schedule_once(self) -> None:
        """启动 pending 队列项，直到达到并发上限。"""
        from vmtools_next.data.models.warehouse import ScanQueueModel
        from datetime import datetime, timezone

        Session = get_session_factory()
        db = Session()
        items = []
        try:
            running = db.query(ScanQueueModel).filter(
                ScanQueueModel.status == "running").count()
            if running >= self._max_concurrent:
                return
            slot = self._max_concurrent - running
            pending = db.query(ScanQueueModel).filter(
                ScanQueueModel.status == "pending").order_by(
                ScanQueueModel.priority.desc(),
                ScanQueueModel.created_at.asc(),
            ).limit(slot).all()
            # 立即置为 running，防止调度器下一轮重复选中同一任务（_start_scan
            # 内部容器发现等耗时阶段会保持 pending，产生竞态导致重复启动）
            # 注意：commit 会 expire 所有 ORM 对象，session 关闭后不能再用这些对象，
            # 因此只把 queue_id 传给 _start_scan，由它在新 session 内重新查询。
            for q in pending:
                q.status = "running"
                q.started_at = datetime.now(timezone.utc)
                db.commit()
                items.append(q.queue_id)
        finally:
            db.close()

        for queue_id in items:
            await self._start_scan(queue_id)

    # ── 容器发现 ──
    async def _discover_containers(self, db, qid: str, wh_id: str, client, engine_type: str) -> list[tuple[int, int, int]]:
        """mineflayer：scan_nearby_blocks 发现半径15格真实容器；失败回退 zone 枚举。"""
        from vmtools_next.data.models.warehouse import StorageZoneModel

        positions: list[tuple[int, int, int]] = []
        max_positions = 10000

        if engine_type == "mineflayer":
            try:
                scan_res = await client.scan_nearby_blocks(
                    radius=15, max_count=max_positions, matching=_CONTAINER_MATCHING)
                blocks = (scan_res or {}).get("blocks") or []
                if blocks:
                    positions = [(b["x"], b["y"], b["z"]) for b in blocks[:max_positions]]
                    logger.info("Scan queue %s discovered %d containers nearby", qid[:8], len(positions))
                    return positions
            except Exception as e:
                logger.warning("scan_nearby_blocks failed, fallback to zones: %s", e)

        # zone 枚举兜底
        zones = db.query(StorageZoneModel).filter(
            StorageZoneModel.warehouse_fk == wh_id).all()
        for zone in zones:
            for x in range(zone.range_min_x, zone.range_max_x + 1):
                for y in range(zone.range_min_y, zone.range_max_y + 1):
                    for z in range(zone.range_min_z, zone.range_max_z + 1):
                        positions.append((x, y, z))
                        if len(positions) >= max_positions:
                            break
                    if len(positions) >= max_positions:
                        break
                if len(positions) >= max_positions:
                    break
            if len(positions) >= max_positions:
                break
        return positions

    # ── 启动单个扫描 ──
    async def _start_scan(self, queue_id: str) -> None:
        """为队列项启动实际扫描。失败则标记 failed 并继续调度。

        ``queue_id`` 来自调度器；本方法在新 session 内重新查询队列项，
        并把 qid/bot_id/warehouse_id 复制到本地，避免 commit 后 ORM 对象
        expire 导致的 DetachedInstanceError（异步进度回调也用本地值）。
        """
        from vmtools_next.core.warehouse_scan_service import mark_scan_started
        from vmtools_next.data.models.warehouse import ScanQueueModel, WarehouseModel
        from vmtools_next.main import get_pool_for_engine
        from vmtools_next.core.bot_engine import resolve_bot_engine

        Session = get_session_factory()
        db = Session()
        qid = queue_id
        bot_id = ""
        wh_id = ""
        try:
            q = db.query(ScanQueueModel).filter(
                ScanQueueModel.queue_id == queue_id).first()
            if not q:
                return
            bot_id = q.bot_id or ""
            wh_id = q.warehouse_id or ""
            # q 保持绑定 session 用于 DB 写入；bot_id/wh_id/qid 用于跨 session 回调

            engine_type = resolve_bot_engine(bot_id, db)
            pool = get_pool_for_engine(engine_type)
            client = pool.get_client(bot_id) if pool else None
            if not client:
                q.status = "failed"
                q.error = f"Bot {bot_id} not connected"
                db.commit()
                await self._broadcast_queue()
                return

            # minihud 适配器 + Servux 就绪检查
            if engine_type == "mineflayer":
                from vmtools_next.adapters.mineflayer.mf_minihud import MfMiniHudAdapter
                minihud = MfMiniHudAdapter(client)
                if not await minihud.ensure_servux(timeout_ms=4000):
                    q.status = "failed"
                    q.error = "Servux 未就绪：服务器未安装 Servux 插件或握手失败"
                    db.commit()
                    await self._broadcast_queue()
                    return
            else:
                from vmtools_next.adapters.mcc.mcc_minihud import MccMiniHudAdapter
                minihud = MccMiniHudAdapter(client)

            # 容器坐标
            container_positions = await self._discover_containers(db, qid, wh_id, client, engine_type)
            if not container_positions:
                q.status = "failed"
                q.error = "未发现容器（zone 为空且 scan_nearby_blocks 无结果）"
                db.commit()
                await self._broadcast_queue()
                return

            # 传送（仓库 teleport_cmd）
            wh = db.query(WarehouseModel).filter(
                WarehouseModel.warehouse_id == wh_id).first()
            teleport_cmd = (wh.logistics_teleport_cmd or "").strip() if wh else ""
            if teleport_cmd and engine_type == "mineflayer":
                try:
                    await client.run_command(teleport_cmd)
                    await asyncio.sleep(3)
                except Exception as e:
                    logger.warning("Teleport to warehouse %s failed: %s", wh_id, e)

            from vmtools_next.core.warehouse_scanner import WarehouseScanner
            scanner = WarehouseScanner(client, minihud)

            # 标记 running
            q.status = "running"
            q.started_at = datetime.now(timezone.utc)
            q.total_containers = len(container_positions)
            q.scanned_containers = 0
            q.items_scanned = 0
            db.commit()
            mark_scan_started(db, wh_id, len(container_positions))
            self._scanners[qid] = scanner
            self._started_at[qid] = time.time()
        finally:
            db.close()

        # 进度回调：Socket.IO + scan_status 落库 + 队列项计数（只用本地 qid/wh_id/bot_id）
        async def on_progress(scanned, total, pos, items):
            elapsed = max(0.001, time.time() - self._started_at[qid])
            speed = round(scanned / elapsed, 2) if elapsed > 0 else 0.0
            eta = round((total - scanned) / speed, 1) if speed > 0 else None
            await sio.emit("scan_progress", {
                "warehouse_id": wh_id,
                "queue_id": qid,
                "scanned": scanned,
                "total": total,
                "items_scanned": items,
                "current_pos": {"x": pos[0], "y": pos[1], "z": pos[2]},
                "progress": round(scanned / total * 100, 1) if total > 0 else 0,
                "speed": speed,
                "eta_seconds": eta,
            })
            # 落库（新开 session）
            S2 = get_session_factory()
            db2 = S2()
            try:
                from vmtools_next.data.models.warehouse import ScanQueueModel, ScanStatusModel
                from vmtools_next.core.warehouse_scan_service import update_scan_progress
                update_scan_progress(db2, wh_id, scanned, total, pos, items)
                qq = db2.query(ScanQueueModel).filter(
                    ScanQueueModel.queue_id == qid).first()
                if qq:
                    qq.scanned_containers = scanned
                    qq.items_scanned = items
                    qq.total_containers = total
                    qq.progress = round(scanned / total * 100, 1) if total > 0 else 0
                    db2.commit()
            finally:
                db2.close()

        scanner.set_progress_callback(on_progress)
        success = await scanner.start_scan(container_positions)
        if success:
            asyncio.create_task(self._watch_completion(qid, scanner))
            await self._broadcast_queue()
        else:
            self._scanners.pop(qid, None)
            self._started_at.pop(qid, None)
            S3 = get_session_factory()
            db3 = S3()
            try:
                from vmtools_next.data.models.warehouse import ScanQueueModel
                qq = db3.query(ScanQueueModel).filter(
                    ScanQueueModel.queue_id == qid).first()
                if qq:
                    qq.status = "failed"
                    qq.error = "Failed to start scan"
                    db3.commit()
            finally:
                db3.close()
            await self._broadcast_queue()

    # ── 完成处理 ──
    async def _watch_completion(self, queue_id: str, scanner) -> None:
        from vmtools_next.core.warehouse_scanner import ScanState
        from vmtools_next.core.warehouse_scan_service import persist_scan_results

        try:
            await scanner._scan_task
        except asyncio.CancelledError:
            return

        Session = get_session_factory()
        db = Session()
        try:
            from vmtools_next.data.models.warehouse import ScanQueueModel, ScanStatusModel
            q = db.query(ScanQueueModel).filter(
                ScanQueueModel.queue_id == queue_id).first()
            if not q:
                return
            total = len(scanner._scan_queue) if scanner._scan_queue else 0
            scanned = len(scanner.results)
            failed = max(0, total - scanned)
            items = getattr(scanner, "_scanned_items", 0)

            if scanner.state == ScanState.COMPLETED:
                summary = persist_scan_results(
                    db, q.warehouse_id, scanner.results,
                    total_containers=total, scanned_containers=scanned,
                    failed_containers=failed, status="finished")
                q.status = "completed"
                q.scanned_containers = scanned
                q.items_scanned = items
                q.finished_at = datetime.now(timezone.utc)
                db.commit()
                await sio.emit("scan_alert", {
                    "type": "success",
                    "queue_id": queue_id,
                    "warehouse_id": q.warehouse_id,
                    "message": f"扫描完成: {summary['containers']} 容器 / {summary['materials']} 种材料 / {summary['total_items']} 物品",
                })
            elif scanner.state == ScanState.CANCELED:
                if scanner.results:
                    persist_scan_results(db, q.warehouse_id, scanner.results,
                                         total_containers=total, scanned_containers=scanned,
                                         failed_containers=failed, status="cancelled")
                q.status = "cancelled"
                q.finished_at = datetime.now(timezone.utc)
                db.commit()
                await sio.emit("scan_alert", {
                    "type": "info", "queue_id": queue_id,
                    "message": f"扫描已取消（已保存 {scanned}/{total} 容器）",
                })
            elif scanner.state == ScanState.FAILED:
                q.status = "failed"
                q.error = "扫描任务异常"
                q.finished_at = datetime.now(timezone.utc)
                db.commit()
                await sio.emit("scan_alert", {"type": "error", "queue_id": queue_id, "message": "扫描失败"})
        except Exception as e:
            logger.error("Persist scan results failed for %s: %s", queue_id, e)
        finally:
            db.close()
            self._scanners.pop(queue_id, None)
            self._started_at.pop(queue_id, None)

        await self._broadcast_queue()
        await self._schedule_once()

    # ── 广播 ──
    async def _broadcast_queue(self) -> None:
        try:
            items = await self.list_queue()
            await sio.emit("scan_queue_update", {"items": items})
        except Exception as e:
            logger.debug("scan_queue_update emit skipped: %s", e)