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


# ── MCC 状态概览（与 MCC 管理页隔离，只读） ──────────────────

class NearestResidence(BaseModel):
    label: str
    owner: str
    world: str
    distance: float  # 与 bot 的水平距离（方块）
    position: dict


class BotCurrentTask(BaseModel):
    type: str          # logistics | mapart | scan
    name: str          # 任务描述，如「物流·铁矿搬运」「地图画·像素龙」
    status: str        # running / paused
    progress: Optional[float] = None


class MccBotStatusItem(BaseModel):
    bot_id: str
    name: str
    status: str                # online / offline / error
    mc_username: str
    current_health: Optional[float] = None
    current_food: Optional[int] = None
    current_location: Optional[dict] = None
    mcp_port: Optional[int] = None
    viewer_port: Optional[int] = None  # 3D 查看器端口（mineflayer，viewer 未启用时为 None）
    last_heartbeat: Optional[str] = None
    nearest_residence: Optional[NearestResidence] = None
    current_task: Optional[BotCurrentTask] = None  # 当前在做的工作（无则空闲）


class MccBotStatusList(BaseModel):
    items: list[MccBotStatusItem]
    residences_total: int = 0


# ── Inventory schemas ──────────────────────

class InventorySlot(BaseModel):
    slot: int
    item_id: str = ""
    display_name: str = ""
    item_name_zh: str = ""  # 中文名（后端 item_names_zh 映射）
    count: int = 0
    max_stack: int = 64
    durability: Optional[int] = None
    max_durability: Optional[int] = None
    nbt: Optional[str] = None
    enchantments: Optional[list] = None  # [{name, lvl}, ...]（mineflayer 端解析）


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
    slot_id: Optional[int] = None  # 前端标准槽位；指定时精确丢弃该槽位（否则按类型全局）


class InventoryMoveRequest(BaseModel):
    """移动/交换背包槽位（mineflayer：bot.moveSlotItem）。槽位为前端标准布局。"""
    slot_id: int
    dest_slot_id: int


class InventoryUseRequest(BaseModel):
    """使用物品（吃食物等，mineflayer：bot.consume）。slot_id 为前端标准槽位，可选。"""
    item_type: Optional[str] = None
    slot_id: Optional[int] = None


# ── 玩家操控（移动控制台） ──

class MoveControlRequest(BaseModel):
    """持续按住/松开控制键（mineflayer setControlState）。"""
    direction: str  # forward | back | left | right | jump | sneak | sprint
    state: bool = True


class LookRequest(BaseModel):
    """视角控制：平滑转向（yaw/pitch 弧度）。"""
    yaw: float
    pitch: Optional[float] = None
    force: bool = False


class SneakRequest(BaseModel):
    """蹲下/站起（state=None 时切换）。"""
    state: Optional[bool] = None
