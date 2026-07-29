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


# ── Inventory schemas ──────────────────────

class InventorySlot(BaseModel):
    slot: int
    item_id: str = ""
    display_name: str = ""
    count: int = 0
    max_stack: int = 64
    durability: Optional[int] = None
    max_durability: Optional[int] = None
    nbt: Optional[str] = None


class InventorySnapshot(BaseModel):
    bot_id: str
    inventory_id: int
    slots: list[InventorySlot]  # 36 main + 9 hotbar + 4 armor + 1 offhand = 50 max
    hotbar: list[int]           # [27..35] slot indices currently in hotbar
    selected_hotbar: int        # currently selected hotbar index (0-8)
    empty_slots: int
    total_items: int


class InventoryActionRequest(BaseModel):
    inventory_id: int = 0
    slot_id: int
    action: str  # LeftClick | RightClick | ShiftClick | DropItemStack | DropSingleItem


class InventorySelectHotbarRequest(BaseModel):
    slot: int  # 0-8 hotbar index


class InventoryDropRequest(BaseModel):
    item_type: str
    count: int = 64
    inventory_id: int = 0
