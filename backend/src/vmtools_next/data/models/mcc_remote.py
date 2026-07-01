"""MCC remote management ORM models.

These tables manage local/container MCC process instances. They are separate
from mcc_bots, which represents a connected automation bot over MCP.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Index, Integer, String, Text

from vmtools_next.data.db import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class MccInstanceModel(Base):
    """A managed MCC process instance with an isolated working directory."""

    __tablename__ = "mcc_instances"

    instance_id = Column(String, primary_key=True)
    slug = Column(String, nullable=False, unique=True, index=True)
    display_name = Column(String, default="", nullable=False)
    bot_id = Column(String, ForeignKey("mcc_bots.bot_id"), nullable=True, index=True)
    account_profile_id = Column(String, ForeignKey("mcc_account_profiles.profile_id"), nullable=True, index=True)

    instance_dir = Column(String, nullable=False)
    binary_mode = Column(String, default="symlink", nullable=False)  # symlink | copy | external
    mcc_binary_path = Column(String, default="", nullable=False)
    launch_command_json = Column(Text, nullable=True)

    status = Column(String, default="created", nullable=False)
    desired_state = Column(String, default="stopped", nullable=False)
    pid = Column(Integer, nullable=True)
    exit_code = Column(Integer, nullable=True)

    mcp_host = Column(String, default="127.0.0.1", nullable=False)
    mcp_port = Column(Integer, nullable=False, unique=True, index=True)
    mcp_auth_token_hash = Column(String, default="", nullable=False)
    mcp_auth_token_secret = Column(Text, nullable=True)
    mcp_auth_token_env = Column(String, default="MCC_MCP_AUTH_TOKEN", nullable=False)

    mc_username = Column(String, default="", nullable=False)
    mc_server_host = Column(String, default="", nullable=False)
    mc_server_port = Column(Integer, default=25565, nullable=False)
    mc_version = Column(String, default="1.21.1", nullable=False)

    organization_id = Column(String, nullable=True, index=True)
    created_by = Column(String, nullable=True, index=True)
    last_started_at = Column(DateTime, nullable=True)
    last_stopped_at = Column(DateTime, nullable=True)
    last_heartbeat_at = Column(DateTime, nullable=True)
    deleted_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=utc_now, nullable=False)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now, nullable=False)

    __table_args__ = (
        Index("idx_mcc_instances_status", "status"),
        Index("idx_mcc_instances_org_status", "organization_id", "status"),
    )


class MccAccountProfileModel(Base):
    """Reusable account profile metadata. Secrets are never returned by APIs."""

    __tablename__ = "mcc_account_profiles"

    profile_id = Column(String, primary_key=True)
    name = Column(String, nullable=False)
    auth_type = Column(String, default="offline", nullable=False)
    username = Column(String, default="", nullable=False)
    password_secret = Column(Text, nullable=True)
    auth_server_url = Column(String, nullable=True)
    auth_api_path = Column(String, nullable=True)
    authlib_injector_path = Column(String, nullable=True)
    mc_server_host = Column(String, default="", nullable=False)
    mc_server_port = Column(Integer, default=25565, nullable=False)
    mc_version = Column(String, default="1.21.1", nullable=False)
    last_login_name = Column(String, nullable=True)
    organization_id = Column(String, nullable=True, index=True)
    created_at = Column(DateTime, default=utc_now, nullable=False)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now, nullable=False)

    __table_args__ = (
        Index("idx_mcc_account_profiles_org", "organization_id"),
    )


class MccProcessEventModel(Base):
    """Lifecycle event for an MCC process."""

    __tablename__ = "mcc_process_events"

    event_id = Column(Integer, primary_key=True, autoincrement=True)
    instance_id = Column(String, ForeignKey("mcc_instances.instance_id"), nullable=False, index=True)
    event_type = Column(String, nullable=False, index=True)
    pid = Column(Integer, nullable=True)
    exit_code = Column(Integer, nullable=True)
    message = Column(Text, default="", nullable=False)
    created_at = Column(DateTime, default=utc_now, nullable=False, index=True)

    __table_args__ = (
        Index("idx_mcc_process_events_instance_time", "instance_id", "created_at"),
    )


class MccTerminalLogModel(Base):
    """Captured terminal line from stdout/stderr/stdin/system."""

    __tablename__ = "mcc_terminal_logs"

    log_id = Column(Integer, primary_key=True, autoincrement=True)
    instance_id = Column(String, ForeignKey("mcc_instances.instance_id"), nullable=False, index=True)
    stream = Column(String, default="stdout", nullable=False)
    seq = Column(Integer, nullable=False)
    content = Column(Text, nullable=False)
    content_masked = Column(Text, nullable=True)
    created_at = Column(DateTime, default=utc_now, nullable=False, index=True)

    __table_args__ = (
        Index("idx_mcc_terminal_logs_instance_seq", "instance_id", "seq"),
        Index("idx_mcc_terminal_logs_instance_time", "instance_id", "created_at"),
    )


class MccFileSnapshotModel(Base):
    """Diff snapshot created when editing text files online."""

    __tablename__ = "mcc_file_snapshots"

    snapshot_id = Column(String, primary_key=True)
    instance_id = Column(String, ForeignKey("mcc_instances.instance_id"), nullable=False, index=True)
    relative_path = Column(String, nullable=False)
    content_hash_before = Column(String, default="", nullable=False)
    content_hash_after = Column(String, default="", nullable=False)
    diff_text = Column(Text, default="", nullable=False)
    created_by = Column(String, nullable=True, index=True)
    created_at = Column(DateTime, default=utc_now, nullable=False)


class MccAuditLogModel(Base):
    """Security audit log for MCC remote-management operations."""

    __tablename__ = "mcc_audit_logs"

    audit_id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String, nullable=True, index=True)
    organization_id = Column(String, nullable=True, index=True)
    instance_id = Column(String, nullable=True, index=True)
    action = Column(String, nullable=False, index=True)
    resource_type = Column(String, default="instance", nullable=False)
    resource_path = Column(String, nullable=True)
    before_json = Column(Text, nullable=True)
    after_json = Column(Text, nullable=True)
    success = Column(Boolean, default=True, nullable=False)
    error_message = Column(Text, nullable=True)
    ip_address = Column(String, nullable=True)
    user_agent = Column(String, nullable=True)
    created_at = Column(DateTime, default=utc_now, nullable=False, index=True)

    __table_args__ = (
        Index("idx_mcc_audit_logs_instance_time", "instance_id", "created_at"),
        Index("idx_mcc_audit_logs_user_time", "user_id", "created_at"),
    )
