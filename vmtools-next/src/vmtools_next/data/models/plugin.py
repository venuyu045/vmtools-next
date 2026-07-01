"""Plugin state ORM model (NEW).

Table: plugin_states

Persists plugin enable/disable state and per-plugin JSON config across
restarts. The PluginManager loads this on startup and syncs in-memory
state on changes.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Column, String, Boolean, DateTime, Text

from vmtools_next.data.db import Base


class PluginStateModel(Base):
    """Persisted state of a loaded plugin."""

    __tablename__ = "plugin_states"

    name = Column(String, primary_key=True)
    version = Column(String, nullable=False)
    enabled = Column(Boolean, default=True, nullable=False)
    config = Column(Text, nullable=True)  # JSON blob of plugin-specific config
    loaded_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    last_reload_at = Column(DateTime, nullable=True)
