"""SQLAlchemy engine, session factory, Base, and Socket.IO server.

Database URL comes from config (server.database_url). On startup,
init_db() creates all tables and ensures the site admin account exists.

Engine and Session are created lazily on first call to init_db() or
get_engine() to avoid importing config at module level.
"""
from __future__ import annotations

import os
import uuid
import pathlib
from typing import Optional

import socketio
from sqlalchemy import create_engine, text
from sqlalchemy.orm import declarative_base, sessionmaker

from vmtools_next.infra.logging import get_logger

logger = get_logger("db")

# ── Socket.IO Server ────────────────────────────────────────────────────

sio = socketio.AsyncServer(async_mode="asgi", cors_allowed_origins="*")

# ── Lazy Engine & Session ───────────────────────────────────────────────

Base = declarative_base()

_engine = None
_SessionLocal = None
_DATABASE_URL: Optional[str] = None


def get_engine():
    """Get or create the SQLAlchemy engine (lazy init)."""
    global _engine, _SessionLocal, _DATABASE_URL
    if _engine is not None:
        return _engine

    from vmtools_next.config import get_config
    config = get_config()
    _DATABASE_URL = config.server.database_url

    # Resolve relative SQLite paths to absolute based on this module's location,
    # so the database is always found regardless of cwd.
    # Module: backend/src/vmtools_next/data/db.py → 5 levels up → project root.
    if _DATABASE_URL.startswith("sqlite:///"):
        db_rel = _DATABASE_URL.removeprefix("sqlite:///")
        db_path = pathlib.Path(db_rel)
        if not db_path.is_absolute():
            # Derive project root from this file's location
            project_root = pathlib.Path(__file__).resolve().parent.parent.parent.parent.parent
            db_path = (project_root / "vmtools-next" / "vmtools-next.db").resolve()
            _DATABASE_URL = f"sqlite:///{db_path}"

    connect_args = {}
    if _DATABASE_URL.startswith("sqlite"):
        connect_args["check_same_thread"] = False

    _engine = create_engine(_DATABASE_URL, connect_args=connect_args, echo=False)

    # SQLite 并发优化：WAL 模式（读写不互斥）+ busy_timeout（写锁等待而非秒失败）
    if _DATABASE_URL.startswith("sqlite"):
        from sqlalchemy import event

        @event.listens_for(_engine, "connect")
        def _set_sqlite_pragma(dbapi_connection, connection_record):
            cursor = dbapi_connection.cursor()
            try:
                cursor.execute("PRAGMA journal_mode=WAL")
                cursor.execute("PRAGMA busy_timeout=5000")
                cursor.execute("PRAGMA synchronous=NORMAL")
            except Exception:
                pass
            finally:
                cursor.close()

    _SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=_engine)
    return _engine


def get_session_factory():
    """Get the SessionLocal factory (lazy init)."""
    if _SessionLocal is None:
        get_engine()
    return _SessionLocal


def get_db():
    """FastAPI dependency yielding a SQLAlchemy session."""
    Session = get_session_factory()
    db = Session()
    try:
        yield db
    finally:
        db.close()


# ── Initialization ──────────────────────────────────────────────────────

def init_db() -> None:
    """Create all tables and ensure site admin exists.

    Called from FastAPI lifespan on startup. For schema migrations
    beyond create_all, use Alembic (`alembic upgrade head`).
    """
    engine = get_engine()
    Session = get_session_factory()

    # Ensure SQLite parent directory exists (for Docker volume mounts)
    if _DATABASE_URL and _DATABASE_URL.startswith("sqlite:///"):
        db_path = _DATABASE_URL.removeprefix("sqlite:///")
        pathlib.Path(db_path).parent.mkdir(parents=True, exist_ok=True)

    # Import all model modules so Base.metadata knows about every table
    from vmtools_next.data.models import (  # noqa: F401
        warehouse, auth, logistics, build, mcc_session, mcc_remote, plugin, monitor, player_tracking,
    )

    Base.metadata.create_all(bind=engine)
    _run_lightweight_migrations(engine)
    _create_indexes(engine)
    _ensure_site_admin(Session)
    _sync_player_tracking(Session)
    logger.info("Database initialized: {}", _DATABASE_URL)


def _sync_player_tracking(Session) -> None:
    """Sync player_tracking_owners DB table into the runtime config."""
    try:
        from vmtools_next.config import get_config as _cfg_get, TrackOwner
        import json as _json
        db = Session()
        try:
            from vmtools_next.data.models.player_tracking import PlayerTrackingOwnerModel
            owners_db = db.query(PlayerTrackingOwnerModel).all()
            if not owners_db:
                return
            owners = [
                TrackOwner(
                    name=o.name,
                    qq_openid=o.qq_openid,
                    track_players=_json.loads(o.track_players_json),
                )
                for o in owners_db
            ]
            # Mutate cached config in-place (don't invalidate cache)
            _cfg_get().player_tracking.owners = owners
            logger.info("Player tracking: synced {} owners from DB to config", len(owners_db))
        finally:
            db.close()
    except Exception:
        pass


def _run_lightweight_migrations(engine) -> None:
    """Apply tiny SQLite-compatible additive migrations for pre-Alembic tables."""
    try:
        with engine.connect() as conn:
            # ── 权限组重构：org_member→user、org_admin→admin（幂等 UPDATE）──
            # 合并"用户"与"组织成员"为用户权限组；"组织管理员"更名为"管理员"。
            try:
                conn.execute(text("UPDATE users SET role='user' WHERE role='org_member'"))
                conn.execute(text("UPDATE users SET role='admin' WHERE role='org_admin'"))
            except Exception as _e:
                logger.warning("Role migration check: %s", _e)
            if _DATABASE_URL and _DATABASE_URL.startswith("sqlite"):
                columns = {row[1] for row in conn.execute(text("PRAGMA table_info(mcc_instances)")).fetchall()}
                if "account_profile_id" not in columns:
                    conn.execute(text("ALTER TABLE mcc_instances ADD COLUMN account_profile_id VARCHAR"))
                if "auto_reconnect" not in columns:
                    conn.execute(text("ALTER TABLE mcc_instances ADD COLUMN auto_reconnect BOOLEAN DEFAULT 0"))
                if "bot_engine" not in columns:
                    conn.execute(text("ALTER TABLE mcc_instances ADD COLUMN bot_engine VARCHAR DEFAULT 'mcc'"))
                if "mcp_host" not in columns:
                    conn.execute(text("ALTER TABLE mcc_instances ADD COLUMN mcp_host VARCHAR DEFAULT '127.0.0.1'"))
                # scan_status 实时进度扩展列（扫描队列）
                try:
                    s_columns = {row[1] for row in conn.execute(text("PRAGMA table_info(scan_status)")).fetchall()}
                    if "items_scanned" not in s_columns:
                        conn.execute(text("ALTER TABLE scan_status ADD COLUMN items_scanned BIGINT DEFAULT 0"))
                    if "started_at" not in s_columns:
                        conn.execute(text("ALTER TABLE scan_status ADD COLUMN started_at DATETIME"))
                    if "finished_at" not in s_columns:
                        conn.execute(text("ALTER TABLE scan_status ADD COLUMN finished_at DATETIME"))
                except Exception as _e:
                    logger.warning("scan_status migration check: %s", _e)
            conn.commit()
    except Exception as e:
        logger.warning("Lightweight migration check: {}", e)


def _create_indexes(engine) -> None:
    """Create additional indexes and utility tables that aren't in ORM definitions."""
    try:
        with engine.connect() as conn:
            # bluemap_cache table (key-value store for BlueMap data persistence)
            conn.execute(text(
                "CREATE TABLE IF NOT EXISTS bluemap_cache ("
                "  cache_key TEXT PRIMARY KEY,"
                "  cache_data TEXT,"
                "  updated_at REAL"
                ")"
            ))
            for sql in (
                "CREATE INDEX IF NOT EXISTS idx_build_tasks_status ON build_tasks (status)",
                "CREATE INDEX IF NOT EXISTS idx_build_tasks_bot ON build_tasks (bot_id)",
                "CREATE INDEX IF NOT EXISTS idx_metrics_snapshot_ts ON metrics_snapshot (timestamp, metric_name)",
                "CREATE INDEX IF NOT EXISTS idx_mcc_instances_status ON mcc_instances (status)",
                "CREATE INDEX IF NOT EXISTS idx_mcc_instances_account_profile ON mcc_instances (account_profile_id)",
                "CREATE INDEX IF NOT EXISTS idx_mcc_terminal_logs_instance_seq ON mcc_terminal_logs (instance_id, seq)",
            ):
                conn.execute(text(sql))
            conn.commit()
    except Exception as e:
        logger.warning("Index creation check: {}", e)


def _ensure_site_admin(Session) -> None:
    """Create or update the site admin account from env vars."""
    import bcrypt
    from vmtools_next.data.models.auth import UserModel

    admin_game_id = os.getenv("SITE_ADMIN_GAME_ID", "VenusYu")
    admin_password = os.getenv("SITE_ADMIN_PASSWORD", "jxy080405")

    db = Session()
    try:
        existing = db.query(UserModel).filter(UserModel.role == "site_admin").first()
        if existing:
            changed = False
            if existing.game_id != admin_game_id:
                existing.game_id = admin_game_id
                existing.display_name = admin_game_id
                changed = True
            if not bcrypt.checkpw(admin_password.encode("utf-8"), existing.password_hash.encode("utf-8")):
                existing.password_hash = bcrypt.hashpw(
                    admin_password.encode("utf-8"), bcrypt.gensalt()
                ).decode("utf-8")
                changed = True
            if changed:
                db.commit()
                logger.info("Site admin updated: {}", admin_game_id)
            return

        if not admin_password:
            admin_password = uuid.uuid4().hex[:12]
            logger.info("Generated site admin password for '{}': {}", admin_game_id, admin_password)

        password_hash = bcrypt.hashpw(
            admin_password.encode("utf-8"), bcrypt.gensalt()
        ).decode("utf-8")
        admin = UserModel(
            id=str(uuid.uuid4()),
            game_id=admin_game_id,
            password_hash=password_hash,
            display_name=admin_game_id,
            role="site_admin",
            status="approved",
            organization_id=None,
        )
        db.add(admin)
        db.commit()
        logger.info("Site admin account created: {}", admin_game_id)
    except Exception as e:
        db.rollback()
        logger.error("Failed to create site admin: {}", e)
    finally:
        db.close()
