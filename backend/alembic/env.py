"""Alembic migration environment.

Reads database URL from VMTools Next config (not alembic.ini), imports all
ORM models so autogenerate can detect schema changes.
"""
from __future__ import annotations

import sys
import pathlib
from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool
from alembic import context

# Ensure src/ is on sys.path so `vmtools_next` package is importable
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))

from vmtools_next.config import get_config  # noqa: E402
from vmtools_next.data.db import Base  # noqa: E402
from vmtools_next.data import models  # noqa: E402,F401 — register all tables

# Alembic config
config = context.config

# Override sqlalchemy.url from VMTools Next config
app_config = get_config()
config.set_main_option("sqlalchemy.url", app_config.server.database_url)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode (emit SQL to stdout)."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode (connect to DB and execute)."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
