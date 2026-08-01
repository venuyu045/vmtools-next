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
from vmtools_next.api.routers.warehouse import router as warehouse_router
from vmtools_next.api.routers.build import router as build_router
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
    _mineflayer_process_manager = MineflayerProcessManager()
    logger.info("Mineflayer Process Manager started")

    # 4. Task Engine — one per engine; each TaskEngine's pool is fixed at
    #    construction, so it can only ever see clients of one engine.
    _task_engine = TaskEngine(_pool)
    _mcc_task_engine = TaskEngine(_mcc_pool)
    _mineflayer_task_engine = TaskEngine(_mineflayer_pool)
    logger.info("Task Engines initialized (primary + mcc + mineflayer)")

    # 5. Plugin Manager
    context = PluginContext(_task_engine, _pool)
    _plugin_manager = PluginManager(context)
    await _plugin_manager.load_builtin()
    await _plugin_manager.start_all()
    logger.info("Plugin Manager started")

    # 5.5 Config Hot-Reload Watcher
    from vmtools_next.infra.config_watcher import ConfigWatcher
    from vmtools_next.config import reload_config as _reload_config

    async def _on_config_change():
        _reload_config()
        logger.info("Config reloaded via hot-reload")
        if _plugin_manager:
            await _plugin_manager.reload_all()

    config_dir = pathlib.Path("config")
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
    await _alert_engine.start()
    logger.info("Monitor & Alert Engine started")

    # 7. Socket.IO event handlers (import triggers @sio.event registration)
    import vmtools_next.api.socketio_handlers  # noqa: F401
    logger.info("Socket.IO event handlers registered")

    # 8. QQ Bot notification service
    from vmtools_next.core.qqbot_notify import start as qqbot_start
    await qqbot_start()

    # 8.5 BlueMap player monitor (replaces sentinel-bot terminal parsing)
    from vmtools_next.core.bluemap_monitor import BlueMapMonitor
    _bluemap_monitor = BlueMapMonitor()
    await _bluemap_monitor.start()

    # 9. Periodic broadcast task
    import asyncio
    broadcast_task = asyncio.create_task(_periodic_broadcast())

    logger.info("Startup complete — listening on {}:{}", config.server.host, config.server.port)
    yield

    # Shutdown
    logger.info("VMTools Next shutting down...")
    from vmtools_next.core.qqbot_notify import stop as qqbot_stop
    await qqbot_stop()
    broadcast_task.cancel()
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
    if _pool:
        await _pool.stop()
    if _mcc_pool:
        await _mcc_pool.stop()
    if _mineflayer_pool:
        await _mineflayer_pool.stop()


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
                for b in db.query(MccBotModel).all():
                    bots.append({
                        "bot_id": b.bot_id,
                        "name": b.name,
                        "status": b.status,
                        "mc_username": b.mc_username,
                        "current_health": b.current_health,
                        "current_food": b.current_food,
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
    app.include_router(warehouse_router)
    app.include_router(build_router)
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
