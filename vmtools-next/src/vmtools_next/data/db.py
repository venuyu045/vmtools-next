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

    connect_args = {}
    if _DATABASE_URL.startswith("sqlite"):
        connect_args["check_same_thread"] = False

    _engine = create_engine(_DATABASE_URL, connect_args=connect_args, echo=False)
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
        warehouse, auth, logistics, build, mcc_session, mcc_remote, plugin, monitor,
    )

    Base.metadata.create_all(bind=engine)
    _run_lightweight_migrations(engine)
    _create_indexes(engine)
    _ensure_site_admin(Session)
    logger.info("Database initialized: {}", _DATABASE_URL)


def _run_lightweight_migrations(engine) -> None:
    """Apply tiny SQLite-compatible additive migrations for pre-Alembic tables."""
    try:
        with engine.connect() as conn:
            if _DATABASE_URL and _DATABASE_URL.startswith("sqlite"):
                columns = {row[1] for row in conn.execute(text("PRAGMA table_info(mcc_instances)")).fetchall()}
                if "account_profile_id" not in columns:
                    conn.execute(text("ALTER TABLE mcc_instances ADD COLUMN account_profile_id VARCHAR"))
            conn.commit()
    except Exception as e:
        logger.warning("Lightweight migration check: {}", e)


def _create_indexes(engine) -> None:
    """Create additional indexes that aren't in ORM definitions."""
    try:
        with engine.connect() as conn:
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
