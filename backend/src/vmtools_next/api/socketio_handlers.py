"""Socket.IO event handlers for vmtools-next.

Registers event handlers on the shared `sio` instance from data.db.
Provides: connect/disconnect, scan_control, logistics_control, build_control,
MCC terminal rooms with JWT authentication.
"""
from __future__ import annotations

from vmtools_next.data.db import sio, get_session_factory
from vmtools_next.infra.logging import get_logger

logger = get_logger("socketio")


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
            return {"user_id": user_id, "organization_id": user.organization_id}
        finally:
            db.close()
    except Exception:
        logger.warning("Socket.IO token validation failed sid={}", sid)
        return None


async def _check_mcc_permission(sid: str, instance_id: str) -> bool:
    """Check if the connected user has permission to access the MCC instance."""
    session = await sio.get_session(sid)
    user = session.get("user")
    if not user:
        return False
    try:
        Session = get_session_factory()
        db = Session()
        try:
            from vmtools_next.data.models.mcc_remote import MccInstanceModel
            instance = db.query(MccInstanceModel).filter(
                MccInstanceModel.instance_id == instance_id,
                MccInstanceModel.deleted_at.is_(None),
            ).first()
            if not instance:
                return False
            if instance.created_by == user["user_id"]:
                return True
            if instance.organization_id and instance.organization_id == user["organization_id"]:
                return True
            return False
        finally:
            db.close()
    except Exception:
        return False


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
        from vmtools_next.main import get_mcc_process_manager

        manager = get_mcc_process_manager()
        if not manager:
            await sio.emit("mcc_terminal_error", {"instance_id": instance_id, "message": "MCC process manager not initialized"}, to=sid)
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
    try:
        from vmtools_next.main import get_mcc_process_manager

        manager = get_mcc_process_manager()
        if not manager:
            await sio.emit("mcc_terminal_error", {"instance_id": instance_id, "message": "MCC process manager not initialized"}, to=sid)
            return
        await manager.write_stdin(instance_id, input_text, append_newline=append_newline)
    except Exception as e:
        logger.error("MCC terminal input error: {}", e)
        await sio.emit("mcc_terminal_error", {"instance_id": instance_id, "message": str(e)}, to=sid)


@sio.on("scan_control")
async def scan_control(sid, data):
    """Handle scan_control from web UI.

    Supported actions: start, pause, resume, cancel
    Required data: action, warehouse_id
    Optional data: bot_id (for start)
    """
    if not isinstance(data, dict):
        await sio.emit("scan_alert", {"type": "error", "message": "Invalid data format"}, to=sid)
        return
    action = data.get("action", "")
    warehouse_id = data.get("warehouse_id", "")
    bot_id = data.get("bot_id", "")
    logger.info("Scan control from {}: action={} warehouse={}", sid, action, warehouse_id)

    try:
        from vmtools_next.main import get_task_engine
        engine = get_task_engine()
        if not engine:
            await sio.emit("scan_alert", {"type": "error", "message": "Task engine not initialized"}, to=sid)
            return

        if action == "start" and warehouse_id:
            # Look up warehouse and start scan
            from vmtools_next.data.db import get_session_factory
            from vmtools_next.data.models.warehouse import WarehouseModel, StorageZoneModel
            Session = get_session_factory()
            db = Session()
            try:
                wh = db.query(WarehouseModel).filter(
                    WarehouseModel.warehouse_id == warehouse_id
                ).first()
                if not wh:
                    await sio.emit("scan_alert", {"type": "error", "message": "Warehouse not found"}, to=sid)
                    return

                # Get container positions from storage zones
                zones = db.query(StorageZoneModel).filter(
                    StorageZoneModel.warehouse_fk == warehouse_id
                ).all()

                container_positions = []
                max_positions = 10000  # Safety limit
                for zone in zones:
                    for x in range(zone.range_min_x, zone.range_max_x + 1):
                        for y in range(zone.range_min_y, zone.range_max_y + 1):
                            for z in range(zone.range_min_z, zone.range_max_z + 1):
                                container_positions.append((x, y, z))
                                if len(container_positions) >= max_positions:
                                    break
                            if len(container_positions) >= max_positions:
                                break
                        if len(container_positions) >= max_positions:
                            break
                    if len(container_positions) >= max_positions:
                        break

                if len(container_positions) >= max_positions:
                    logger.warning("Container positions truncated to %d for warehouse %s",
                                   max_positions, warehouse_id)

                if not container_positions:
                    await sio.emit("scan_alert", {"type": "error", "message": "No containers found in warehouse zones"}, to=sid)
                    return

                # Use the bot's scanner (requires bot_id)
                if not bot_id:
                    await sio.emit("scan_alert", {"type": "error", "message": "bot_id required for scan"}, to=sid)
                    return

                client = engine._pool.get_client(bot_id)
                if not client:
                    await sio.emit("scan_alert", {"type": "error", "message": f"Bot {bot_id} not connected"}, to=sid)
                    return

                from vmtools_next.adapters.mcc.mcc_minihud import MccMiniHudAdapter
                from vmtools_next.core.warehouse_scanner import WarehouseScanner

                minihud = MccMiniHudAdapter(client)
                scanner = WarehouseScanner(client, minihud)

                # Set up progress callback to emit updates via Socket.IO
                async def on_progress(scanned, total, pos):
                    await sio.emit("scan_progress", {
                        "warehouse_id": warehouse_id,
                        "scanned": scanned,
                        "total": total,
                        "current_pos": {"x": pos[0], "y": pos[1], "z": pos[2]},
                        "progress": round(scanned / total * 100, 1) if total > 0 else 0,
                    })

                scanner.set_progress_callback(on_progress)
                success = await scanner.start_scan(container_positions)
                if success:
                    await sio.emit("scan_alert", {"type": "info", "message": f"Scan started: {len(container_positions)} containers"}, to=sid)
                else:
                    await sio.emit("scan_alert", {"type": "error", "message": "Failed to start scan"}, to=sid)
            finally:
                db.close()
        else:
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
        from vmtools_next.main import get_task_engine
        engine = get_task_engine()
        if not engine:
            await sio.emit("logistics_alert", {"type": "error", "message": "Task engine not initialized"}, to=sid)
            return

        if action == "start" and template_id and bot_id:
            # Start a new logistics task
            run_id = await engine.start_logistics_task(bot_id, template_id)
            if run_id:
                await sio.emit("task_progress", {"run_id": run_id, "status": "running"}, to=sid)
            else:
                await sio.emit("logistics_alert", {"type": "error", "message": "Failed to start logistics task"}, to=sid)
        elif action == "stop" and run_id:
            await engine.stop_task(run_id)
        elif action == "pause" and run_id:
            await engine.pause_task(run_id)
        elif action == "resume" and run_id:
            await engine.resume_task(run_id)
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
        from vmtools_next.main import get_task_engine
        engine = get_task_engine()
        if not engine:
            await sio.emit("build_alert", {"type": "error", "message": "Task engine not initialized"}, to=sid)
            return

        if action == "start":
            bot_id = data.get("bot_id")
            projection_path = data.get("projection_file_path")
            if not bot_id or not projection_path:
                await sio.emit("build_alert", {"type": "error", "message": "bot_id and projection_file_path required"}, to=sid)
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
            await engine.stop_task(task_id)
        elif action == "pause" and task_id:
            await engine.pause_task(task_id)
        elif action == "resume" and task_id:
            await engine.resume_task(task_id)
    except Exception as e:
        logger.error("Build control error: {}", e)
        await sio.emit("build_alert", {"type": "error", "message": str(e)}, to=sid)


def _build_initial_payload(user_info: dict | None = None) -> dict:
    """Build initial sync payload for newly connected client.

    Scoped to the user's organization. Site admins see all data.
    """
    org_id = (user_info or {}).get("organization_id")
    user_id = (user_info or {}).get("user_id")

    Session = get_session_factory()
    db = Session()
    try:
        from vmtools_next.data.models.logistics import MccBotModel, LogisticsTaskRunModel
        from vmtools_next.data.models.warehouse import WarehouseModel

        # Build bot query, scoped by org
        bot_query = db.query(MccBotModel)
        warehouse_query = db.query(WarehouseModel)
        run_query = db.query(LogisticsTaskRunModel).filter(
            LogisticsTaskRunModel.status.in_(["running", "paused"])
        )

        # For non-site-admin users, filter by organization
        if org_id:
            bot_query = bot_query.filter(MccBotModel.organization_id == org_id)
            warehouse_query = warehouse_query.filter(WarehouseModel.organization_id == org_id)

        bots = []
        for b in bot_query.all():
            bots.append({
                "bot_id": b.bot_id,
                "name": b.name,
                "status": b.status,
                "mc_username": b.mc_username,
                "current_health": b.current_health,
                "current_food": b.current_food,
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
