"""Socket.IO event handlers for vmtools-next.

Registers event handlers on the shared `sio` instance from data.db.
Provides: connect/disconnect, scan_control, logistics_control, build_control.
"""
from __future__ import annotations

from vmtools_next.data.db import sio, get_session_factory
from vmtools_next.infra.logging import get_logger

logger = get_logger("socketio")


@sio.event
async def connect(sid, environ, auth):
    """Client connected — push initial sync data."""
    logger.info("Socket.IO client connected: {}", sid)
    try:
        payload = _build_initial_payload()
        await sio.emit("sync_update", payload, to=sid)
    except Exception as e:
        logger.warning("Failed to send initial sync: {}", e)


@sio.event
async def disconnect(sid):
    logger.info("Socket.IO client disconnected: {}", sid)


@sio.on("scan_control")
async def scan_control(sid, data):
    """Handle scan_control from web UI.

    Supported actions: start, pause, resume, cancel
    Required data: action, warehouse_id
    Optional data: bot_id (for start)
    """
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
                for zone in zones:
                    for x in range(zone.range_min_x, zone.range_max_x + 1):
                        for y in range(zone.range_min_y, zone.range_max_y + 1):
                            for z in range(zone.range_min_z, zone.range_max_z + 1):
                                container_positions.append((x, y, z))

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


def _build_initial_payload() -> dict:
    """Build initial sync payload for newly connected client."""
    Session = get_session_factory()
    db = Session()
    try:
        from vmtools_next.data.models.logistics import MccBotModel, LogisticsTaskRunModel
        from vmtools_next.data.models.warehouse import WarehouseModel

        bots = []
        for b in db.query(MccBotModel).all():
            bots.append({
                "bot_id": b.bot_id,
                "name": b.name,
                "status": b.status,
                "mc_username": b.mc_username,
                "current_health": b.current_health,
                "current_food": b.current_food,
            })

        warehouses = []
        for w in db.query(WarehouseModel).all():
            warehouses.append({
                "warehouse_id": w.warehouse_id,
                "name": w.name,
                "container_count": w.container_count,
                "total_items": w.total_items,
            })

        active_runs = []
        for r in db.query(LogisticsTaskRunModel).filter(
            LogisticsTaskRunModel.status.in_(["running", "paused"])
        ).all():
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
