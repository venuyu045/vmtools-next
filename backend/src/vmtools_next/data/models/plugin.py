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


class PluginBotStateModel(Base):
    """Per-bot override of a plugin's enabled state (2026-08-13).

    Table: plugin_bot_states

    按 bot 维度控制插件启停（如某 bot 只开 auto_afkfarm、不开 chat_responder）。
    事件分发时该表记录优先于 plugin_states.enabled（全局）：
      - 有记录 → 用记录值
      - 无记录 → 回退全局 enabled（默认启用）
    """

    __tablename__ = "plugin_bot_states"

    bot_id = Column(String, primary_key=True)
    plugin_name = Column(String, primary_key=True)
    enabled = Column(Boolean, default=True, nullable=False)
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc),
                        onupdate=lambda: datetime.now(timezone.utc), nullable=False)
