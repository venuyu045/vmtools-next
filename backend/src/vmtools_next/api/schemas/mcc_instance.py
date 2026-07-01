"""Schemas for MCC remote instance management."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field, field_validator


class MccInstanceCreate(BaseModel):
    slug: str = Field(min_length=1, max_length=64)
    display_name: str = ""
    bot_id: Optional[str] = None
    account_profile_id: Optional[str] = None
    binary_mode: str = "symlink"
    mc_username: str = ""
    mc_server_host: str = ""
    mc_server_port: int = 25565
    mc_version: str = "1.21.1"

    @field_validator("slug")
    @classmethod
    def validate_slug(cls, value: str) -> str:
        import re

        normalized = value.strip().lower()
        if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,63}", normalized):
            raise ValueError("slug must match [a-z0-9][a-z0-9_-]{0,63}")
        return normalized

    @field_validator("binary_mode")
    @classmethod
    def validate_binary_mode(cls, value: str) -> str:
        if value not in {"symlink", "copy", "external"}:
            raise ValueError("binary_mode must be symlink, copy, or external")
        return value


class MccInstanceUpdate(BaseModel):
    display_name: Optional[str] = None
    bot_id: Optional[str] = None
    account_profile_id: Optional[str] = None
    mc_username: Optional[str] = None
    mc_server_host: Optional[str] = None
    mc_server_port: Optional[int] = None
    mc_version: Optional[str] = None


class MccInstanceStartRequest(BaseModel):
    env: dict[str, str] = Field(default_factory=dict)


class MccInstanceStopRequest(BaseModel):
    force: bool = False
    timeout_seconds: float = 10.0


class MccTerminalInputRequest(BaseModel):
    input: str = Field(min_length=1, max_length=4096)
    append_newline: bool = True


class MccFileEntryResponse(BaseModel):
    name: str
    path: str
    type: str
    size: int
    updated_at: float
    editable: bool
    downloadable: bool = True
    language: str = ""


class MccFileListResponse(BaseModel):
    path: str
    breadcrumbs: list[dict[str, str]] = Field(default_factory=list)
    items: list[MccFileEntryResponse]


class MccFileTreeNode(BaseModel):
    name: str
    path: str
    type: str
    children: list["MccFileTreeNode"] = Field(default_factory=list)


class MccFileTreeResponse(BaseModel):
    items: list[MccFileTreeNode]


class MccFileContentResponse(BaseModel):
    path: str
    content: str
    encoding: str
    size: int
    language: str
    masked: bool
    updated_at: float


class MccFileWriteRequest(BaseModel):
    path: str = Field(min_length=1, max_length=512)
    content: str = Field(max_length=1_048_576)
    encoding: str = "utf-8"


class MccFileCreateRequest(BaseModel):
    path: str = Field(min_length=1, max_length=512)
    content: str = Field(default="", max_length=1_398_104)
    encoding: str = "utf-8"
    overwrite: bool = False


class MccDirectoryCreateRequest(BaseModel):
    path: str = Field(min_length=1, max_length=512)
    overwrite: bool = False


class MccFileRenameRequest(BaseModel):
    source_path: str = Field(min_length=1, max_length=512)
    target_path: str = Field(min_length=1, max_length=512)
    overwrite: bool = False


class MccFileSaveResponse(BaseModel):
    path: str
    size: int | None = None
    snapshot_id: str | None = None
    diff: str | None = None
    masked_secrets_preserved: bool = False


class MccAccountConfigResponse(BaseModel):
    auth_type: str
    username: str
    password_set: bool
    auth_server_url: str = ""
    auth_api_path: str = ""
    authlib_injector_path: str = ""
    mc_server_host: str
    mc_server_port: int
    mc_version: str
    mcp_port: int
    mcp_auth_token_env: str


class MccAccountConfigUpdate(BaseModel):
    auth_type: str = Field(default="offline")
    username: str = Field(min_length=1, max_length=128)
    password: Optional[str] = Field(default=None, max_length=512)
    auth_server_url: str = ""
    auth_api_path: str = ""
    authlib_injector_path: str = ""
    mc_server_host: str = ""
    mc_server_port: int = Field(default=25565, ge=1, le=65535)
    mc_version: str = "1.21.1"

    @field_validator("auth_type")
    @classmethod
    def validate_auth_type(cls, value: str) -> str:
        if value not in {"offline", "microsoft", "mojang", "yggdrasil", "custom"}:
            raise ValueError("auth_type must be offline, microsoft, mojang, yggdrasil, or custom")
        return value


class MccAccountConfigSaveResponse(BaseModel):
    config: MccAccountConfigResponse
    snapshot_id: str
    diff: str
    restart_required: bool = True


class MccAccountProfileCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    auth_type: str = "offline"
    username: str = Field(min_length=1, max_length=128)
    password: Optional[str] = Field(default=None, max_length=512)
    auth_server_url: str = ""
    auth_api_path: str = ""
    authlib_injector_path: str = ""
    mc_server_host: str = ""
    mc_server_port: int = Field(default=25565, ge=1, le=65535)
    mc_version: str = "1.21.1"

    @field_validator("auth_type")
    @classmethod
    def validate_auth_type(cls, value: str) -> str:
        if value not in {"offline", "microsoft", "mojang", "yggdrasil", "custom"}:
            raise ValueError("auth_type must be offline, microsoft, mojang, yggdrasil, or custom")
        return value


class MccAccountProfileUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=128)
    auth_type: Optional[str] = None
    username: Optional[str] = Field(default=None, min_length=1, max_length=128)
    password: Optional[str] = Field(default=None, max_length=512)
    clear_password: bool = False
    auth_server_url: Optional[str] = None
    auth_api_path: Optional[str] = None
    authlib_injector_path: Optional[str] = None
    mc_server_host: Optional[str] = None
    mc_server_port: Optional[int] = Field(default=None, ge=1, le=65535)
    mc_version: Optional[str] = None

    @field_validator("auth_type")
    @classmethod
    def validate_auth_type(cls, value: Optional[str]) -> Optional[str]:
        if value is not None and value not in {"offline", "microsoft", "mojang", "yggdrasil", "custom"}:
            raise ValueError("auth_type must be offline, microsoft, mojang, yggdrasil, or custom")
        return value


class MccAccountProfileResponse(BaseModel):
    profile_id: str
    name: str
    auth_type: str
    username: str
    password_set: bool
    auth_server_url: str | None = None
    auth_api_path: str | None = None
    authlib_injector_path: str | None = None
    mc_server_host: str
    mc_server_port: int
    mc_version: str
    last_login_name: str | None = None
    organization_id: str | None = None
    created_at: datetime
    updated_at: datetime


class MccAccountProfileListResponse(BaseModel):
    items: list[MccAccountProfileResponse]
    total: int


class MccApplyAccountProfileRequest(BaseModel):
    profile_id: str


class MccInstanceResponse(BaseModel):
    instance_id: str
    slug: str
    display_name: str
    bot_id: Optional[str] = None
    account_profile_id: Optional[str] = None
    instance_dir: str
    binary_mode: str
    mcc_binary_path: str
    status: str
    desired_state: str
    pid: Optional[int] = None
    exit_code: Optional[int] = None
    mcp_host: str
    mcp_port: int
    mcp_auth_token_env: str
    mc_username: str
    mc_server_host: str
    mc_server_port: int
    mc_version: str
    organization_id: Optional[str] = None
    created_by: Optional[str] = None
    last_started_at: Optional[datetime] = None
    last_stopped_at: Optional[datetime] = None
    last_heartbeat_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class MccInstanceListResponse(BaseModel):
    items: list[MccInstanceResponse]
    total: int


class MccTerminalLogResponse(BaseModel):
    seq: int
    stream: str
    content: str
    created_at: datetime


class MccTerminalHistoryResponse(BaseModel):
    items: list[MccTerminalLogResponse]
    last_seq: int


class MccProcessEventResponse(BaseModel):
    event_id: int
    instance_id: str
    event_type: str
    pid: Optional[int] = None
    exit_code: Optional[int] = None
    message: str
    created_at: datetime

    model_config = {"from_attributes": True}


class MccStartStopResponse(BaseModel):
    instance_id: str
    status: str
    pid: Optional[int] = None
    mcp_port: int
    message: str = ""
    extra: dict[str, Any] = Field(default_factory=dict)
