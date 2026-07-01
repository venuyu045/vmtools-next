"""MCC MCP session ORM model (NEW).

Table: mcc_mcp_sessions

Tracks the live MCP HTTP connection state for each bot. The MccSessionPool
manages one MccMcpClient instance per bot and updates this row every 5s
via get_session_status() health checks.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Column, String, Integer, DateTime, ForeignKey

from vmtools_next.data.db import Base


class MccMcpSessionModel(Base):
    """Live MCP HTTP session state for a bot.

    One row per bot (1:1 with mcc_bots). Updated by MccSessionPool's
    background health-check task.
    """

    __tablename__ = "mcc_mcp_sessions"

    bot_id = Column(String, ForeignKey("mcc_bots.bot_id"), primary_key=True)
    endpoint = Column(String, nullable=False)  # e.g. http://127.0.0.1:33333/mcp
    auth_token_env = Column(String, default="MCC_MCP_AUTH_TOKEN")
    protocol = Column(String, default="mcp", nullable=False)  # mcp | ws
    status = Column(String, default="offline", nullable=False)  # offline|connecting|online|error
    last_heartbeat = Column(DateTime, nullable=True)
    last_event_id = Column(Integer, default=0)  # monotonic event pointer for polling
    mcc_version = Column(String, nullable=True)  # MCC version reported by GetSessionStatus
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
