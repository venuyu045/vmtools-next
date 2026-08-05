"""Socket.IO event handlers for vmtools-next.

Registers event handlers on the shared `sio` instance from data.db.
Provides: connect/disconnect, scan_control, logistics_control, build_control,
MCC terminal rooms with JWT authentication.
"""
from __future__ import annotations

from vmtools_next.data.db import sio, get_session_factory
from vmtools_next.infra.logging import get_logger

import asyncio

logger = get_logger("socketio")


async def _task_control_all(action: str, task_id: str) -> bool:
    """Apply a control action to a task across all active task engines.

    stop/pause/resume only carry a task_id (no bot_id), so we ask each
    engine in order — the owner is the first one that reports success.
    """
    from vmtools_next.main import get_all_task_engines

    for engine in get_all_task_engines():
        try:
            if action == "stop":
                ok = await engine.stop_task(task_id)
            elif action == "pause":
                ok = await engine.pause_task(task_id)
            elif action == "resume":
                ok = await engine.resume_task(task_id)
            else:
                return False
            if ok:
                return True
        except Exception as e:
            logger.warning("Task engine {} {} failed: {}", action, task_id, e)
    return False


async def _verify_socketio_token(sid: str, auth: dict | None) -> dict | None:
    """Validate JWT token from Socket.IO auth handshake.

    Returns {"user_id": ..., "organization_id": ...} on success, None on failure.
    """
    token = (auth or {}).get("token", "")
    if not token:
        logger.warning("Socket.IO connect rejected: missing token sid={}", sid)
        return None
    try:
        import jwt
        from vmtools_next.config import get_config

        config = get_config()
        payload = jwt.decode(token, config.server.secret_key, algorithms=[config.server.jwt_algorithm])
        user_id = payload.get("sub")
        if not user_id:
            return None
        Session = get_session_factory()
        db = Session()
        try:
            from vmtools_next.data.models.auth import UserModel
            user = db.query(UserModel).filter(UserModel.id == user_id).first()
            if not user or user.status != "approved":
                return None
            return {"user_id": user_id, "organization_id": user.organization_id, "role": user.role}
        finally:
            db.close()
    except Exception:
        logger.warning("Socket.IO token validation failed sid={}", sid)
        return None


async def _check_mcc_permission(sid: str, instance_id: str) -> bool:
    """Check if the connected user has permission to access the MCC instance terminal.

    Delegates to ``MccInstanceService.get_instance`` so Socket.IO and REST share
    exactly the same scoping rules (site_admin → all, otherwise same org).
    """
    session = await sio.get_session(sid)
    user_info = session.get("user")
    if not user_info:
        return False
    try:
        from vmtools_next.core.mcc_instance_service import MccInstanceService
        Session = get_session_factory()
        db = Session()
        try:
            from vmtools_next.data.models.auth import UserModel
            user = db.query(UserModel).filter(UserModel.id == user_info.get("user_id")).first()
            if not user:
                return False
            MccInstanceService().get_instance(db, user, instance_id)
            return True
        except Exception:
            return False
        finally:
            db.close()
    except Exception:
        return False


async def _user_from_session(sid: str):
    """Resolve the UserModel for a socket sid, or None when unavailable."""
    session = await sio.get_session(sid)
    user_info = session.get("user")
    if not user_info or not user_info.get("user_id"):
        return None
    Session = get_session_factory()
    db = Session()
    try:
        from vmtools_next.data.models.auth import UserModel
        return db.query(UserModel).filter(UserModel.id == user_info["user_id"]).first()
    finally:
        db.close()


@sio.event
async def connect(sid, environ, auth):
    """Client connected — validate JWT and push initial sync data."""
    user_info = await _verify_socketio_token(sid, auth)
    if not user_info:
        logger.warning("Socket.IO connect rejected: invalid token sid={}", sid)
        await sio.disconnect(sid)
        return
    await sio.save_session(sid, {"user": user_info})
    logger.info("Socket.IO client connected: {} user={}", sid, user_info["user_id"])
    try:
        payload = _build_initial_payload(user_info)
        await sio.emit("sync_update", payload, to=sid)
    except Exception as e:
        logger.warning("Failed to send initial sync: {}", e)


@sio.event
async def disconnect(sid):
    logger.info("Socket.IO client disconnected: {}", sid)


async def _terminal_manager_for(instance_id: str):
    """根据实例的 bot_engine 选择对应的进程管理器（MCC / Mineflayer）。

    MCC 与 MF 实例共用同一张 mcc_instances 表，但终端数据由各自的
    ProcessManager 维护（MccProcessManager / MineflayerProcessManager）。
    """
    try:
        from vmtools_next.data.models.mcc_remote import MccInstanceModel
        Session = get_session_factory()
        db = Session()
        try:
            inst = db.query(MccInstanceModel).filter(
                MccInstanceModel.instance_id == instance_id,
                MccInstanceModel.deleted_at.is_(None),
            ).first()
            engine = (inst.bot_engine if inst else None) or "mcc"
        finally:
            db.close()
    except Exception:
        engine = "mcc"

    if engine == "mineflayer":
        from vmtools_next.main import get_mineflayer_process_manager
        return get_mineflayer_process_manager()
    from vmtools_next.main import get_mcc_process_manager
    return get_mcc_process_manager()


@sio.on("mcc_join_instance")
async def mcc_join_instance(sid, data):
    """Subscribe a socket to one MCC instance terminal room."""
    if not isinstance(data, dict):
        await sio.emit("mcc_terminal_error", {"message": "Invalid data format"}, to=sid)
        return
    instance_id = data.get("instance_id")
    tail_lines = int(data.get("tail_lines", 300))
    if not instance_id:
        await sio.emit("mcc_terminal_error", {"message": "instance_id required"}, to=sid)
        return
    if not await _check_mcc_permission(sid, instance_id):
        await sio.emit("mcc_terminal_error", {"instance_id": instance_id, "message": "Permission denied"}, to=sid)
        return
    try:
        manager = await _terminal_manager_for(instance_id)
        if not manager:
            await sio.emit("mcc_terminal_error", {"instance_id": instance_id, "message": "Process manager not initialized"}, to=sid)
            return
        await sio.enter_room(sid, f"mcc:{instance_id}")
        lines = manager.tail_logs(instance_id, tail=max(1, min(tail_lines, 1000)))
        await sio.emit("mcc_terminal_snapshot", {
            "instance_id": instance_id,
            "items": [
                {
                    "seq": line.seq,
                    "stream": line.stream,
                    "content": line.content,
                    "created_at": line.created_at.isoformat(),
                }
                for line in lines
            ],
            "last_seq": lines[-1].seq if lines else 0,
        }, to=sid)
    except Exception as e:
        logger.error("MCC join instance error: {}", e)
        await sio.emit("mcc_terminal_error", {"instance_id": instance_id, "message": str(e)}, to=sid)


@sio.on("mcc_leave_instance")
async def mcc_leave_instance(sid, data):
    instance_id = data.get("instance_id") if isinstance(data, dict) else None
    if instance_id:
        await sio.leave_room(sid, f"mcc:{instance_id}")


@sio.on("mcc_terminal_input")
async def mcc_terminal_input(sid, data):
    if not isinstance(data, dict):
        await sio.emit("mcc_terminal_error", {"message": "Invalid data format"}, to=sid)
        return
    instance_id = data.get("instance_id")
    input_text = data.get("input", "")
    append_newline = bool((data or {}).get("append_newline", True))
    if not instance_id or not input_text:
        await sio.emit("mcc_terminal_error", {"instance_id": instance_id, "message": "instance_id and input required"}, to=sid)
        return
    if not await _check_mcc_permission(sid, instance_id):
        await sio.emit("mcc_terminal_error", {"instance_id": instance_id, "message": "Permission denied"}, to=sid)
        return

    # Audit terminal input, mirroring the REST endpoint's action semantics.
    from vmtools_next.core.mcc_audit_log_service import MccAuditLogService
    audit = MccAuditLogService()
    user = await _user_from_session(sid)
    db = get_session_factory()()
    try:
        manager = await _terminal_manager_for(instance_id)
        if not manager:
            await sio.emit("mcc_terminal_error", {"instance_id": instance_id, "message": "Process manager not initialized"}, to=sid)
            return
        await manager.write_stdin(instance_id, input_text, append_newline=append_newline, source_sid=sid)
        audit.log(db, user=user, action="terminal.input", resource_type="terminal", instance_id=instance_id)
        db.commit()
    except Exception as e:
        db.rollback()
        logger.error("MCC terminal input error: {}", e)
        audit.log(db, user=user, action="terminal.input", resource_type="terminal", instance_id=instance_id, success=False, error_message=str(e))
        db.commit()
        await sio.emit("mcc_terminal_error", {"instance_id": instance_id, "message": str(e)}, to=sid)
    finally:
        db.close()


@sio.on("mcc_terminal_resize")
async def mcc_terminal_resize(sid, data):
    """Resize the PTY window for a running MCC instance."""
    if not isinstance(data, dict):
        return
    instance_id = data.get("instance_id")
    cols = data.get("cols")
    rows = data.get("rows")
    if not instance_id or cols is None or rows is None:
        return
    if not await _check_mcc_permission(sid, instance_id):
        return
    try:
        manager = await _terminal_manager_for(instance_id)
        if not manager:
            return
        await manager.resize_terminal(instance_id, int(cols), int(rows))
    except Exception as e:
        logger.warning("MCC terminal resize error: {}", e)


# 仓库扫描实例管理：warehouse_id → {"scanner": WarehouseScanner, "bot_id": str}
_SCANNERS: dict[str, dict] = {}

# mineflayer scan_nearby_blocks 匹配的容器方块（逗号分隔）
_CONTAINER_MATCHING = (
    "chest,trapped_chest,barrel,hopper,dispenser,dropper,furnace,blast_furnace,"
    "smoker,brewing_stand,ender_chest,shulker_box,white_shulker_box,orange_shulker_box,"
    "magenta_shulker_box,light_blue_shulker_box,yellow_shulker_box,lime_shulker_box,"
    "pink_shulker_box,gray_shulker_box,light_gray_shulker_box,cyan_shulker_box,"
    "purple_shulker_box,blue_shulker_box,brown_shulker_box,green_shulker_box,red_shulker_box,black_shulker_box"
)


async def _watch_scan_completion(warehouse_id: str) -> None:
    """Wait for a scanner task to finish, then persist results and clean up."""
    from vmtools_next.core.warehouse_scanner import ScanState
    entry = _SCANNERS.get(warehouse_id)
    if not entry:
        return
    scanner = entry["scanner"]
    try:
        await scanner._scan_task
    except asyncio.CancelledError:
        return

    from vmtools_next.core.warehouse_scan_service import persist_scan_results
    Session = get_session_factory()
    db = Session()
    try:
        total = len(scanner._scan_queue) if scanner._scan_queue else 0
        scanned = len(scanner.results)
        failed = max(0, total - scanned)
        if scanner.state == ScanState.COMPLETED:
            summary = persist_scan_results(
                db, warehouse_id, scanner.results,
                total_containers=total, scanned_containers=scanned,
                failed_containers=failed, status="finished",
            )
            await sio.emit("scan_alert", {
                "type": "success",
                "message": f"扫描完成: {summary['containers']} 容器 / {summary['materials']} 种材料 / {summary['total_items']} 物品",
            })
        elif scanner.state == ScanState.CANCELED:
            # 保留已扫描部分
            if scanner.results:
                persist_scan_results(db, warehouse_id, scanner.results,
                                     total_containers=total, scanned_containers=scanned,
                                     failed_containers=failed, status="cancelled")
            await sio.emit("scan_alert", {"type": "info", "message": f"扫描已取消（已保存 {scanned}/{total} 容器）"})
        elif scanner.state == ScanState.FAILED:
            await sio.emit("scan_alert", {"type": "error", "message": "扫描失败"})
    except Exception as e:
        logger.error("Persist scan results failed for {}: {}", warehouse_id, e)
        await sio.emit("scan_alert", {"type": "error", "message": f"扫描结果保存失败: {e}"})
    finally:
        db.close()
        _SCANNERS.pop(warehouse_id, None)


@sio.on("scan_control")
async def scan_control(sid, data):
    """Handle scan_control from web UI — 通过扫描队列调度。

    Supported actions: start (入队), pause, resume, cancel
    Required data:
      start: action, warehouse_id, bot_id
      控制: action, queue_id (或 warehouse_id 自动解析)
    """
    if not isinstance(data, dict):
        await sio.emit("scan_alert", {"type": "error", "message": "Invalid data format"}, to=sid)
        return
    action = data.get("action", "")
    warehouse_id = data.get("warehouse_id", "")
    bot_id = data.get("bot_id", "")
    queue_id = data.get("queue_id", "")
    logger.info("Scan control from {}: action={} warehouse={} bot={} queue={}",
                sid, action, warehouse_id, bot_id, queue_id)

    try:
        from vmtools_next.main import get_scan_queue_manager
        qm = get_scan_queue_manager()
        if not qm:
            await sio.emit("scan_alert", {"type": "error", "message": "扫描队列管理器未初始化"}, to=sid)
            return

        if action == "start":
            if not warehouse_id or not bot_id:
                await sio.emit("scan_alert", {"type": "error", "message": "start 需要 warehouse_id 和 bot_id"}, to=sid)
                return
            result = await qm.enqueue(warehouse_id, bot_id)
            if result.get("ok"):
                await sio.emit("scan_alert", {"type": "info", "message": f"已加入扫描队列 (queue={result['queue_id'][:8]})"}, to=sid)
            else:
                await sio.emit("scan_alert", {"type": "error", "message": result.get("error", "入队失败")}, to=sid)
            return

        if action in ("pause", "resume", "cancel"):
            # 允许只传 warehouse_id：自动解析该仓库当前活动的队列项
            if not queue_id and warehouse_id:
                Session = get_session_factory()
                db = Session()
                try:
                    from vmtools_next.data.models.warehouse import ScanQueueModel
                    q = db.query(ScanQueueModel).filter(
                        ScanQueueModel.warehouse_id == warehouse_id,
                        ScanQueueModel.status.in_(["pending", "running", "paused"]),
                    ).order_by(ScanQueueModel.created_at.desc()).first()
                    if q:
                        queue_id = q.queue_id
                finally:
                    db.close()
            if not queue_id:
                await sio.emit("scan_alert", {"type": "error", "message": "未找到活动的扫描任务"}, to=sid)
                return
            result = await qm.control(queue_id, action)
            if result.get("ok"):
                msg = {"pause": "扫描已暂停", "resume": "扫描已继续", "cancel": "扫描已取消"}.get(action, action)
                await sio.emit("scan_alert", {"type": "info", "message": msg}, to=sid)
            else:
                await sio.emit("scan_alert", {"type": "error", "message": result.get("error", "操作失败")}, to=sid)
            return

        await sio.emit("scan_alert", {"type": "error", "message": f"Unknown scan action: {action}"}, to=sid)
    except Exception as e:
        logger.error("Scan control error: {}", e)
        await sio.emit("scan_alert", {"type": "error", "message": str(e)}, to=sid)


@sio.on("logistics_control")
async def logistics_control(sid, data):
    """Handle logistics task control commands."""
    if not isinstance(data, dict):
        await sio.emit("logistics_alert", {"type": "error", "message": "Invalid data format"}, to=sid)
        return
    action = data.get("action", "")
    run_id = data.get("run_id")
    template_id = data.get("template_id")
    bot_id = data.get("bot_id")
    logger.info("Logistics control from {}: {} run={}", sid, action, run_id)

    try:
        if action == "start" and template_id and bot_id:
            # 按 bot 的引擎选择对应 TaskEngine
            from vmtools_next.main import get_task_engine_for_bot
            from vmtools_next.data.db import get_session_factory as _gsf
            db = _gsf()()
            try:
                engine = get_task_engine_for_bot(bot_id, db)
            finally:
                db.close()
            if not engine:
                await sio.emit("logistics_alert", {"type": "error", "message": "Task engine not initialized"}, to=sid)
                return
            # Start a new logistics task
            run_id = await engine.start_logistics_task(bot_id, template_id)
            if run_id:
                await sio.emit("task_progress", {"run_id": run_id, "status": "running"}, to=sid)
            else:
                await sio.emit("logistics_alert", {"type": "error", "message": "Failed to start logistics task"}, to=sid)
        elif action == "stop" and run_id:
            await _task_control_all("stop", run_id)
        elif action == "pause" and run_id:
            await _task_control_all("pause", run_id)
        elif action == "resume" and run_id:
            await _task_control_all("resume", run_id)
    except Exception as e:
        logger.error("Logistics control error: {}", e)
        await sio.emit("logistics_alert", {"type": "error", "message": str(e)}, to=sid)


@sio.on("build_control")
async def build_control(sid, data):
    """Handle build task control commands."""
    if not isinstance(data, dict):
        await sio.emit("build_alert", {"type": "error", "message": "Invalid data format"}, to=sid)
        return
    action = data.get("action", "")
    task_id = data.get("task_id")
    logger.info("Build control from {}: {} task={}", sid, action, task_id)

    try:
        if action == "start":
            bot_id = data.get("bot_id")
            projection_path = data.get("projection_file_path")
            if not bot_id or not projection_path:
                await sio.emit("build_alert", {"type": "error", "message": "bot_id and projection_file_path required"}, to=sid)
                return
            # 按 bot 的引擎选择对应 TaskEngine
            from vmtools_next.main import get_task_engine_for_bot
            from vmtools_next.data.db import get_session_factory as _gsf
            db = _gsf()()
            try:
                engine = get_task_engine_for_bot(bot_id, db)
            finally:
                db.close()
            if not engine:
                await sio.emit("build_alert", {"type": "error", "message": "Task engine not initialized"}, to=sid)
                return
            task_id_result = await engine.start_build_task(
                bot_id, projection_path,
                data.get("origin_x", 0), data.get("origin_y", 0), data.get("origin_z", 0)
            )
            if task_id_result:
                await sio.emit("build_alert", {"type": "info", "message": f"Build started: {task_id_result}"}, to=sid)
            else:
                await sio.emit("build_alert", {"type": "error", "message": "Failed to start build"}, to=sid)
        elif action == "stop" and task_id:
            await _task_control_all("stop", task_id)
        elif action == "pause" and task_id:
            await _task_control_all("pause", task_id)
        elif action == "resume" and task_id:
            await _task_control_all("resume", task_id)
    except Exception as e:
        logger.error("Build control error: {}", e)
        await sio.emit("build_alert", {"type": "error", "message": str(e)}, to=sid)


def _build_initial_payload(user_info: dict | None = None) -> dict:
    """Build initial sync payload for newly connected client.

    Organization isolation removed — all data is visible to any approved user.
    """
    Session = get_session_factory()
    db = Session()
    try:
        from vmtools_next.data.models.logistics import MccBotModel, LogisticsTaskRunModel
        from vmtools_next.data.models.warehouse import WarehouseModel

        # Build bot query
        bot_query = db.query(MccBotModel)
        warehouse_query = db.query(WarehouseModel)
        run_query = db.query(LogisticsTaskRunModel).filter(
            LogisticsTaskRunModel.status.in_(["running", "paused"])
        )

        bots = []
        import json as _json
        for b in bot_query.all():
            try:
                _loc = _json.loads(b.current_location) if b.current_location else None
            except Exception:
                _loc = None
            bots.append({
                "bot_id": b.bot_id,
                "name": b.name,
                "status": b.status,
                "mc_username": b.mc_username,
                "current_health": b.current_health,
                "current_food": b.current_food,
                "current_location": _loc,
            })

        warehouses = []
        for w in warehouse_query.all():
            warehouses.append({
                "warehouse_id": w.warehouse_id,
                "name": w.name,
                "container_count": w.container_count,
                "total_items": w.total_items,
            })

        active_runs = []
        for r in run_query.all():
            active_runs.append({
                "run_id": r.run_id,
                "template_id": r.template_id,
                "bot_id": r.bot_id,
                "status": r.status,
                "progress": r.progress,
            })

        return {
            "bots": bots,
            "warehouses": warehouses,
            "active_task_runs": active_runs,
        }
    except Exception as e:
        logger.warning("Failed to build initial payload: {}", e)
        return {"bots": [], "warehouses": [], "active_task_runs": []}
    finally:
        db.close()


# ──────────────────────────────────────────────
# Map Art Build — Socket.IO room management
# ──────────────────────────────────────────────

@sio.event
async def build_map_join(sid, data: dict):
    """Client joins a map art build task's real-time room.

    Frontend emits: { task_id: "xxx" }
    Backend: joins room "build_{task_id}", pushes build_map_init
    """
    task_id = data.get("task_id", "")
    if not task_id:
        return
    room = f"build_{task_id}"
    sio.enter_room(sid, room)
    logger.debug("Socket.IO {} joined room {}", sid, room)


@sio.event
async def build_map_leave(sid, data: dict):
    """Client leaves a map art build task room."""
    task_id = data.get("task_id", "")
    if not task_id:
        return
    room = f"build_{task_id}"
    sio.leave_room(sid, room)


@sio.event
async def build_map_request_blocks(sid, data: dict):
    """Client requests block states chunk for 3D view.

    Frontend emits: { task_id, chunk: { x_start, x_end, z_start, z_end } }
    Backend responds with build_map_chunk event.
    """
    from sqlalchemy.orm import Session
    task_id = data.get("task_id", "")
    chunk = data.get("chunk", {})
    if not task_id:
        return

    SessionLocal = get_session_factory()
    db: Session = SessionLocal()
    try:
        from vmtools_next.data.models.build_map_art import MapArtBlockState
        blocks = db.query(MapArtBlockState).filter(
            MapArtBlockState.task_id == task_id,
            MapArtBlockState.x >= chunk.get("x_start", 0),
            MapArtBlockState.x <= chunk.get("x_end", 127),
            MapArtBlockState.z >= chunk.get("z_start", 0),
            MapArtBlockState.z <= chunk.get("z_end", 127),
        ).all()
        await sio.emit("build_map_chunk", {
            "task_id": task_id,
            "chunk": chunk,
            "blocks": [
                {"x": b.x, "y": b.y, "z": b.z,
                 "expected": b.expected_block, "actual": b.actual_block,
                 "placed": b.placed, "verified": b.verified}
                for b in blocks
            ],
        }, to=sid)
    except Exception as e:
        logger.warning("build_map_request_blocks error: {}", e)
    finally:
        db.close()
