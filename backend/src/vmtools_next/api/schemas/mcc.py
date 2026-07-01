"""MCC Bot schemas."""
from __future__ import annotations

from pydantic import BaseModel
from typing import Optional


class MccBotCreate(BaseModel):
    bot_id: str
    name: str = ""
    ws_host: str = "127.0.0.1"
    ws_port: int = 8043
    ws_password: str = ""
    mc_username: str = ""
    mc_account_type: str = "offline"
    mc_server_host: str = ""
    mc_server_port: int = 25565
    organization_id: Optional[str] = None


class MccBotUpdate(BaseModel):
    name: Optional[str] = None
    ws_host: Optional[str] = None
    ws_port: Optional[int] = None
    ws_password: Optional[str] = None


class MccBotResponse(BaseModel):
    bot_id: str
    name: str
    status: str
    mc_username: str
    mc_server_host: str
    current_task_run_id: Optional[str] = None
    current_build_task_id: Optional[str] = None
    current_health: float = 20.0
    current_food: int = 20
    organization_id: Optional[str] = None


class MccBotConnectRequest(BaseModel):
    host: str = "127.0.0.1"
    port: int = 33333
    auth_token: Optional[str] = None
