"""FastAPI application entry point.

Lifespan initializes: logging → database → (future: MCC pool, task engine, plugins).
Routers are mounted incrementally as phases complete.
"""
from __future__ import annotations

import pathlib
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

import socketio

from vmtools_next.config import get_config
from vmtools_next.infra.logging import setup_logging, get_logger
from vmtools_next.data.db import init_db, sio
from vmtools_next.api.routers.health import router as health_router
from vmtools_next.api.routers.auth import router as auth_router
from vmtools_next.api.routers.admin_users import router as admin_users_router
from vmtools_next.api.routers.warehouse import router as warehouse_router, materials_router
from vmtools_next.api.routers.mcc_bot import router as mcc_bot_router
from vmtools_next.api.routers.mcc_instances import router as mcc_instances_router
from vmtools_next.api.routers.config import router as config_router
from vmtools_next.api.routers.plugin import router as plugin_router
from vmtools_next.api.routers.monitor import router as monitor_router
from vmtools_next.api.routers.migration import router as migration_router
from vmtools_next.api.routers.logistics import router as logistics_router
from vmtools_next.api.routers.projection import router as projection_router
from vmtools_next.api.routers.player_tracking import router as player_tracking_router
from vmtools_next.api.routers.bluemap_api import router as bluemap_router
from vmtools_next.api.routers.build_map_art import router as map_art_router
from vmtools_next.adapters.mcc.mcc_session_pool import MccSessionPool
from vmtools_next.adapters.mineflayer.mineflayer_session_pool import MineflayerSessionPool
from vmtools_next.core.task_engine import TaskEngine
from vmtools_next.core.mcc_process_manager import MccProcessManager
from vmtools_next.core.mineflayer_process_manager import MineflayerProcessManager
from vmtools_next.plugins.base import PluginContext
from vmtools_next.plugins.manager import PluginManager
from vmtools_next.infra.monitor import MonitorCollector
from vmtools_next.infra.alerts import AlertEngine

logger = get_logger("main")
BASE_DIR = pathlib.Path(__file__).resolve().parent

# Global instances (initialized in lifespan)
_pool: MccSessionPool | MineflayerSessionPool = None
_mcc_pool: MccSessionPool | None = None
_mineflayer_pool: MineflayerSessionPool | None = None
_task_engine: TaskEngine = None
_mcc_task_engine: TaskEngine | None = None
_mineflayer_task_engine: TaskEngine | None = None
_plugin_manager: PluginManager = None
_monitor: MonitorCollector = None
_alert_engine: AlertEngine = None
_mcc_process_manager: MccProcessManager = None
_mineflayer_process_manager: MineflayerProcessManager = None
_bluemap_monitor: "BlueMapMonitor" = None
_scan_queue_manager: "ScanQueueManager" = None


async def _alert_notify_callback(name: str, severity: str, message: str, value: float) -> None:
    """告警触发回调：Socket.IO 推送前端时间线/通知 + QQ 群广播（若 QQ Bot 启用）。

    由 AlertEngine 在规则命中时调用（main.py lifespan 注册）。
    """
    try:
        import time as _time
        from vmtools_next.data.db import sio
        from vmtools_next.core.qqbot_notify import broadcast
        payload = {
            "timestamp": _time.time(),
            "name": name,
            "severity": severity,
            "message": message,
            "value": value,
        }
        await sio.emit("alert", payload)
        await broadcast(f"⚠️ [监控告警·{severity}] {message}")
    except Exception:
        pass


def get_pool() -> MccSessionPool | MineflayerSessionPool:
    return _pool


def get_pool_for_engine(engine: str) -> MccSessionPool | MineflayerSessionPool | None:
    """Return the session pool matching the given bot engine ('mcc' | 'mineflayer')."""
    if engine == "mineflayer":
        return _mineflayer_pool if _mineflayer_pool is not None else _pool
    if engine == "mcc":
        return _mcc_pool if _mcc_pool is not None else _pool
    return _pool


def get_task_engine_for_bot(bot_id: str, db) -> TaskEngine | None:
    """Return the TaskEngine matching a bot's engine, or None before startup."""
    from vmtools_next.core.bot_engine import resolve_bot_engine

    if _mcc_task_engine is None and _mineflayer_task_engine is None:
        return None
    engine = resolve_bot_engine(bot_id, db)
    if engine == "mineflayer":
        return _mineflayer_task_engine
    return _mcc_task_engine if _mcc_task_engine is not None else _task_engine


def get_task_engine() -> TaskEngine:
    return _task_engine


def get_all_task_engines() -> list:
    """All active task engines, primary first, deduplicated.

    Used by task control handlers (stop/pause/resume) that only know a
    task_id — the owning engine is the first one that reports success.
    """
    engines = []
    for e in (_task_engine, _mcc_task_engine, _mineflayer_task_engine):
        if e is not None and e not in engines:
            engines.append(e)
    return engines


def get_monitor() -> MonitorCollector:
    return _monitor


def get_alert_engine() -> AlertEngine:
    return _alert_engine


def get_plugin_manager() -> PluginManager:
    return _plugin_manager


def get_mcc_process_manager() -> MccProcessManager:
    return _mcc_process_manager


def get_mineflayer_process_manager() -> MineflayerProcessManager:
    return _mineflayer_process_manager


def get_bluemap_monitor() -> "BlueMapMonitor":
    return _bluemap_monitor


def get_scan_queue_manager() -> "ScanQueueManager":
    """返回全局扫描队列管理器（lifespan 初始化）。"""
    return _scan_queue_manager


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup & shutdown lifecycle."""
    global _pool, _task_engine, _plugin_manager, _monitor, _alert_engine, _mcc_process_manager, _mineflayer_process_manager, _bluemap_monitor, _mcc_pool, _mineflayer_pool, _mcc_task_engine, _mineflayer_task_engine
    config = get_config()

    # 1. Logging
    setup_logging(log_dir="logs", debug=config.generic.debug_logging)
    logger.info("VMTools Next starting up (v{})", "0.1.0")

    # 2. Database
    init_db()
    logger.info("Database initialized: {}", config.server.database_url)

    # 3. Session Pools — BOTH engines coexist: each instance routes by its own bot_engine.
    #    The "primary" engine is decided by config (used as the fallback pool for bot
    #    operations that don't carry an engine — e.g. the /api/bots MCP bridge).
    use_mineflayer = config.mineflayer.enabled
    _pool = MineflayerSessionPool() if use_mineflayer else MccSessionPool()
    logger.info("Using {} bot engine as primary pool",
                "Mineflayer" if use_mineflayer else "MCC")
    # Always create both pools so either engine's instances can connect at runtime.
    _mcc_pool = MccSessionPool()
    _mineflayer_pool = MineflayerSessionPool()
    await _pool.start()
    await _mcc_pool.start()
    await _mineflayer_pool.start()
    logger.info("Session Pools started (mcc + mineflayer)")

    # 3.5 Process Managers — start BOTH so instances with either bot_engine can run.
    #    (MccProcessManager.start() spawns the MCC runtime watcher; MineflayerProcessManager
    #     is lazy and only spawns node processes on demand.)
    _mcc_process_manager = MccProcessManager()
    await _mcc_process_manager.start()
    logger.info("MCC Process Manager started")
    # 说明：MCC 实例恢复（desired_state=running）后的 MCP 自动连接由
    # MccProcessManager.start_instance 内部统一调度（_auto_connect_mcp），
    # 覆盖 REST start / restart / 崩溃自启 / 启动恢复全部路径，此处不再重复调度。
    _mineflayer_process_manager = MineflayerProcessManager()
    await _mineflayer_process_manager.start()  # 恢复 desired_state=running 的 MF 实例
    logger.info("Mineflayer Process Manager started")

    # 4. Task Engine — one per engine; each TaskEngine's pool is fixed at
    #    construction, so it can only ever see clients of one engine.
    _task_engine = TaskEngine(_pool)
    _mcc_task_engine = TaskEngine(_mcc_pool)
    _mineflayer_task_engine = TaskEngine(_mineflayer_pool)
    logger.info("Task Engines initialized (primary + mcc + mineflayer)")

    # 5. Plugin Manager — 插件体系仅服务 mineflayer 引擎（MCC 为固定 C# 客户端，
    #    不需要额外插件）。上下文绑定 mineflayer 的 TaskEngine 与 SessionPool，
    #    插件可经 pool.get_client(bot_id) 拿到 MineflayerBridgeClient 调用 WS 桥接方法。
    context = PluginContext(_mineflayer_task_engine, _mineflayer_pool)
    _plugin_manager = PluginManager(context)
    await _plugin_manager.load_builtin()
    await _plugin_manager.start_all()
    logger.info("Plugin Manager started (engine=mineflayer)")

    # 5.5 Config Hot-Reload Watcher
    from vmtools_next.infra.config_watcher import ConfigWatcher
    from vmtools_next.config import reload_config as _reload_config
    from vmtools_next.config import get_config_dir

    async def _on_config_change():
        _reload_config()
        logger.info("Config reloaded via hot-reload")
        if _plugin_manager:
            await _plugin_manager.reload_all()

    config_dir = get_config_dir()  # 与 _find_config_dir 保持一致（模块路径，而非 cwd）
    if config_dir.is_dir():
        _config_watcher = ConfigWatcher(
            config_dir=str(config_dir),
            on_change=_on_config_change,
        )
        await _config_watcher.start()
    else:
        logger.debug("Config directory not found, hot-reload disabled")

    # 6. Monitor & Alerts
    _monitor = MonitorCollector()
    await _monitor.start()
    _alert_engine = AlertEngine()
    _alert_engine.add_default_rules()
    _alert_engine.set_metrics_provider(_monitor.get_latest)
    # 告警触发 → QQ 群广播 + Socket.IO 推送（前端告警时间线/通知）
    _alert_engine.set_callback(_alert_notify_callback)
    await _alert_engine.start()
    logger.info("Monitor & Alert Engine started")

    # 7. Socket.IO event handlers (import triggers @sio.event registration)
    import vmtools_next.api.socketio_handlers  # noqa: F401
    logger.info("Socket.IO event handlers registered")

    # 7.5 扫描队列管理器（依赖 sio / pools）
    from vmtools_next.core.scan_queue_manager import ScanQueueManager
    global _scan_queue_manager
    _scan_queue_manager = ScanQueueManager(
        max_concurrent_scans=getattr(config, "scan_max_concurrent_scans", 2),
    )
    await _scan_queue_manager.start()
    logger.info("Scan Queue Manager started")

    # 8. QQ Bot notification service
    from vmtools_next.core.qqbot_notify import start as qqbot_start
    await qqbot_start()

    # 8.5 BlueMap player monitor (replaces sentinel-bot terminal parsing)
    from vmtools_next.core.bluemap_monitor import BlueMapMonitor
    _bluemap_monitor = BlueMapMonitor()
    await _bluemap_monitor.start()

    # 9. Periodic broadcast task + MCP 连接对账（兜底补连）
    import asyncio
    broadcast_task = asyncio.create_task(_periodic_broadcast())
    mcp_reconcile_task = asyncio.create_task(_mcp_reconcile_loop())

    logger.info("Startup complete — listening on {}:{}", config.server.host, config.server.port)
    yield

    # Shutdown
    logger.info("VMTools Next shutting down...")
    from vmtools_next.core.qqbot_notify import stop as qqbot_stop
    await qqbot_stop()
    broadcast_task.cancel()
    mcp_reconcile_task.cancel()
    if _bluemap_monitor:
        await _bluemap_monitor.stop()
    if _monitor:
        await _monitor.stop()
    if _alert_engine:
        await _alert_engine.stop()
    if _plugin_manager:
        await _plugin_manager.stop_all()
    if _mcc_process_manager:
        await _mcc_process_manager.stop()
    if _mineflayer_process_manager:
        await _mineflayer_process_manager.stop_all()
    if _scan_queue_manager:
        await _scan_queue_manager.stop()
    if _pool:
        await _pool.stop()
    if _mcc_pool:
        await _mcc_pool.stop()
    if _mineflayer_pool:
        await _mineflayer_pool.stop()


async def _mcp_reconcile_loop(interval: float = 30.0):
    """周期性对账：status=running 且有 bot_id 的实例，若对应引擎池无连接则补连。

    兜底场景：bot 在实例启动后才绑定、自动连接全部失败、后端重启竞态等，
    确保「实例上线但 MCP/WS 未自动连接」时状态仍能及时更新。
    单实例 60s 内不重复尝试，避免连接风暴。
    """
    import asyncio
    import time as _time

    _last_attempt: dict[str, float] = {}
    while True:
        await asyncio.sleep(interval)
        try:
            from vmtools_next.data.db import get_session_factory
            from vmtools_next.data.models.mcc_remote import MccInstanceModel

            Session = get_session_factory()
            db = Session()
            try:
                instances = db.query(MccInstanceModel).filter(
                    MccInstanceModel.deleted_at.is_(None),
                    MccInstanceModel.status == "running",
                    MccInstanceModel.bot_id.isnot(None),
                ).all()
                from vmtools_next.core.mcc_security import reveal_secret
                rows = [
                    (i.instance_id, i.bot_id, i.bot_engine or "mcc",
                     i.mcp_host or "127.0.0.1", i.mcp_port or 33333,
                     reveal_secret(i.mcp_auth_token_secret) or None)
                    for i in instances
                ]
            finally:
                db.close()

            now = _time.monotonic()
            for instance_id, bot_id, engine, host, port, token in rows:
                if now - _last_attempt.get(instance_id, 0.0) < 60.0:
                    continue
                _last_attempt[instance_id] = now
                try:
                    from vmtools_next.main import get_pool_for_engine
                    pool = get_pool_for_engine(engine)
                    if not pool:
                        continue
                    st = pool.get_bot_status(bot_id)
                    if st.get("status") == "online":
                        continue
                    logger.info("MCP reconcile: connecting running instance {} bot={} engine={}",
                                instance_id[:8], bot_id, engine)
                    if engine == "mineflayer":
                        from vmtools_next.main import get_mineflayer_process_manager
                        mgr = get_mineflayer_process_manager()
                        ws_port = mgr.get_ws_port(instance_id) if mgr else None
                        if ws_port:
                            await pool.connect_bot(bot_id, port=ws_port)
                    else:
                        await pool.connect_bot(bot_id, host=host, port=port, auth_token=token)
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    logger.debug("MCP reconcile attempt failed for {}: {}", instance_id, exc)
        except asyncio.CancelledError:
            break
        except Exception as exc:
            logger.warning("MCP reconcile loop error: {}", exc)


async def _periodic_broadcast():
    """Broadcast bot/task status to all connected clients every 5 seconds."""
    import asyncio
    import time
    while True:
        await asyncio.sleep(5)
        try:
            from vmtools_next.data.db import sio, get_session_factory
            from vmtools_next.data.models.logistics import MccBotModel, LogisticsTaskRunModel

            Session = get_session_factory()
            db = Session()
            try:
                bots = []
                import json as _json
                for b in db.query(MccBotModel).all():
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

                await sio.emit("sync_update", {
                    "bots": bots,
                    "active_task_runs": active_runs,
                    "timestamp": time.time(),
                })
            finally:
                db.close()
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.warning("Periodic broadcast error: {}", e)


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    config = get_config()

    app = FastAPI(
        title="VMTools Next",
        description="MCC-based server-side automation for Minecraft building & logistics",
        version="0.1.0",
        lifespan=lifespan,
    )

    # CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=config.server.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Routers
    app.include_router(health_router)
    app.include_router(auth_router)
    app.include_router(admin_users_router)
    app.include_router(warehouse_router)
    app.include_router(materials_router)
    app.include_router(mcc_bot_router)
    app.include_router(mcc_instances_router)
    app.include_router(config_router)
    app.include_router(plugin_router)
    app.include_router(monitor_router)
    app.include_router(migration_router)
    app.include_router(logistics_router)
    app.include_router(projection_router)
    app.include_router(player_tracking_router)
    app.include_router(bluemap_router)
    app.include_router(map_art_router)

    # Static files (Web UI — will be populated in phase 6)
    static_dir = BASE_DIR.parent.parent / "static"
    if static_dir.is_dir():
        app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    # SPA fallback (serves index.html for non-API routes)
    @app.get("/{full_path:path}")
    def spa_index(full_path: str):
        if full_path.startswith(("api/", "static/")):
            raise HTTPException(status_code=404, detail="Not found")
        index = BASE_DIR.parent.parent / "static" / "index.html"
        if index.is_file():
            return FileResponse(str(index))
        return {"message": "VMTools Next API", "docs": "/docs"}

    return app


# Build the ASGI app: Socket.IO wrapping FastAPI
app = create_app()
sio_app = socketio.ASGIApp(sio, other_asgi_app=app)


def run():
    """Entry point for `vmtools-next` console script and `python -m vmtools_next.main`."""
    import uvicorn

    config = get_config()
    debug = config.server.debug
    uvicorn.run(
        "vmtools_next.main:sio_app" if debug else sio_app,
        host=config.server.host,
        port=config.server.port,
        reload=debug,
        log_level="debug" if debug else "info",
    )


if __name__ == "__main__":
    run()
