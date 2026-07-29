"""MCC Bot management API routes."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from vmtools_next.api.deps import get_db, get_current_user
from vmtools_next.api.schemas.mcc import (
    MccBotCreate, MccBotResponse, MccBotConnectRequest,
    InventorySnapshot, InventorySlot, InventoryActionRequest,
    InventorySelectHotbarRequest, InventoryDropRequest,
)
from vmtools_next.data.models.logistics import MccBotModel
from vmtools_next.adapters.mcc.mcc_mcp_client import MccMcpError

router = APIRouter(prefix="/api/mcc-bots", tags=["mcc-bots"])


@router.get("", response_model=list[MccBotResponse])
def list_bots(db: Session = Depends(get_db), user=Depends(get_current_user)):
    """List all MCC bots."""
    bots = db.query(MccBotModel).all()
    return [MccBotResponse(
        bot_id=b.bot_id,
        name=b.name,
        status=b.status,
        mc_username=b.mc_username,
        mc_server_host=b.mc_server_host,
        current_task_run_id=b.current_task_run_id,
        current_build_task_id=b.current_build_task_id,
        current_health=b.current_health,
        current_food=b.current_food,
        organization_id=b.organization_id,
    ) for b in bots]


@router.post("", response_model=MccBotResponse)
def create_bot(data: MccBotCreate, db: Session = Depends(get_db),
               user=Depends(get_current_user)):
    """Register a new MCC bot."""
    existing = db.query(MccBotModel).filter(MccBotModel.bot_id == data.bot_id).first()
    if existing:
        raise HTTPException(400, "Bot already exists")
    bot = MccBotModel(**data.model_dump())
    db.add(bot)
    db.commit()
    db.refresh(bot)
    return MccBotResponse(
        bot_id=bot.bot_id, name=bot.name, status=bot.status,
        mc_username=bot.mc_username, mc_server_host=bot.mc_server_host,
        organization_id=bot.organization_id,
    )


@router.get("/{bot_id}", response_model=MccBotResponse)
def get_bot(bot_id: str, db: Session = Depends(get_db), user=Depends(get_current_user)):
    """Get a specific bot."""
    bot = db.query(MccBotModel).filter(MccBotModel.bot_id == bot_id).first()
    if not bot:
        raise HTTPException(404, "Bot not found")
    return MccBotResponse(
        bot_id=bot.bot_id, name=bot.name, status=bot.status,
        mc_username=bot.mc_username, mc_server_host=bot.mc_server_host,
        current_task_run_id=bot.current_task_run_id,
        current_build_task_id=bot.current_build_task_id,
        current_health=bot.current_health, current_food=bot.current_food,
        organization_id=bot.organization_id,
    )


@router.delete("/{bot_id}")
def delete_bot(bot_id: str, db: Session = Depends(get_db), user=Depends(get_current_user)):
    """Delete a bot."""
    bot = db.query(MccBotModel).filter(MccBotModel.bot_id == bot_id).first()
    if not bot:
        raise HTTPException(404, "Bot not found")
    db.delete(bot)
    db.commit()
    return {"status": "deleted"}


@router.post("/{bot_id}/connect")
async def connect_bot(bot_id: str, data: MccBotConnectRequest,
                       db: Session = Depends(get_db), user=Depends(get_current_user)):
    """Connect a bot to MCC MCP server."""
    bot = db.query(MccBotModel).filter(MccBotModel.bot_id == bot_id).first()
    if not bot:
        raise HTTPException(404, "Bot not found")

    # Get pool from app state (injected by lifespan)
    from vmtools_next.main import get_pool
    pool = get_pool()
    if not pool:
        raise HTTPException(500, "MCC pool not initialized")

    success = await pool.connect_bot(bot_id, data.host, data.port, data.auth_token)
    bot.status = "online" if success else "error"
    db.commit()

    return {"bot_id": bot_id, "status": bot.status, "connected": success}


@router.post("/{bot_id}/disconnect")
async def disconnect_bot(bot_id: str, db: Session = Depends(get_db),
                          user=Depends(get_current_user)):
    """Disconnect a bot."""
    from vmtools_next.main import get_pool
    pool = get_pool()
    if pool:
        await pool.disconnect_bot(bot_id)

    bot = db.query(MccBotModel).filter(MccBotModel.bot_id == bot_id).first()
    if bot:
        bot.status = "offline"
        db.commit()

    return {"bot_id": bot_id, "status": "offline"}


# ── Inventory endpoints ──────────────────────

async def _get_mcp_client(bot_id: str, mcp_port: int = 0):
    """Get MccMcpClient from session pool, or connect directly as fallback."""
    from vmtools_next.main import get_pool
    from vmtools_next.adapters.mcc.mcc_mcp_client import MccMcpClient
    pool = get_pool()
    if pool:
        client = pool.get_client(bot_id)
        if client:
            return client, False  # (client, owned)

    # Fallback: try common MCP ports
    ports = [mcp_port] if mcp_port else [33333, 33335, 33334, 33336]
    last_err = None
    for port in ports:
        client = MccMcpClient(host="127.0.0.1", port=port, timeout_read=10)
        try:
            ok = await client.connect()
            if ok:
                return client, True
        except Exception as e:
            last_err = str(e)
            continue
    raise HTTPException(503, f"无法连接 MCC MCP (tried ports {ports}): {last_err or 'all failed'}")


def _parse_slot(s: dict, sid: int) -> InventorySlot:
    return InventorySlot(
        slot=sid,
        item_id=s.get("type", s.get("itemId", "")) or "",
        display_name=s.get("name", s.get("displayName", "")),
        count=s.get("count", s.get("amount", 0)) or 0,
        max_stack=s.get("maxStackSize", 64),
    )


@router.get("/{bot_id}/inventory")
async def get_inventory(bot_id: str, mcp_port: int = 0):
    """Get bot's player inventory snapshot (36 + hotbar + armor + offhand)."""
    client, owned = await _get_mcp_client(bot_id, mcp_port)
    try:
        snap = await client.get_inventory_snapshot(inventory_id=0)
        data = snap.get("data", snap)
    except MccMcpError as e:
        raise HTTPException(502, f"MCP error: {str(e) or repr(e)}")
    finally:
        if owned: await client.disconnect()

    all_items = data.get("items", []) or []
    slots = [_parse_slot(s, i) for i, s in enumerate(all_items) if s.get("type") or s.get("itemId")]
    hotbar = data.get("hotbar", []) or list(range(27, 36))
    selected = data.get("selectedHotbar", data.get("selectedSlot", 0)) or 0

    return InventorySnapshot(
        bot_id=bot_id,
        inventory_id=0,
        slots=slots,
        hotbar=hotbar,
        selected_hotbar=selected,
        empty_slots=max(0, 50 - len(all_items)),
        total_items=sum(s.get("count", s.get("amount", 0)) or 0 for s in (all_items or [])),
    )


@router.post("/{bot_id}/inventory/action")
async def inventory_action(bot_id: str, data: InventoryActionRequest):
    """Perform a slot action: LeftClick, RightClick, ShiftClick, DropItemStack, DropSingleItem."""
    client, owned = await _get_mcp_client(bot_id)
    try:
        result = await client.inventory_window_action(
            inventory_id=data.inventory_id,
            slot_id=data.slot_id,
            action_type=data.action,
        )
        return {"success": True, "action": data.action, "slot": data.slot_id, "result": result}
    except MccMcpError as e:
        raise HTTPException(502, f"MCP error: {str(e) or repr(e)}")
    finally:
        if owned: await client.disconnect()


@router.post("/{bot_id}/inventory/drop")
async def inventory_drop(bot_id: str, data: InventoryDropRequest):
    """Drop items from inventory by type."""
    client, owned = await _get_mcp_client(bot_id)
    try:
        result = await client.drop_inventory_item(
            item_type=data.item_type,
            count=data.count,
            inventory_id=data.inventory_id,
        )
        return {"success": True, "dropped": data.item_type, "count": data.count, "result": result}
    except MccMcpError as e:
        raise HTTPException(502, f"MCP error: {str(e) or repr(e)}")
    finally:
        if owned: await client.disconnect()


@router.post("/{bot_id}/inventory/select-hotbar")
async def inventory_select_hotbar(bot_id: str, data: InventorySelectHotbarRequest):
    """Select a hotbar slot (0-8)."""
    client, owned = await _get_mcp_client(bot_id)
    try:
        result = await client.change_hotbar_slot(data.slot)
        return {"success": True, "slot": data.slot, "result": result}
    except MccMcpError as e:
        raise HTTPException(502, f"MCP error: {str(e) or repr(e)}")
    finally:
        if owned: await client.disconnect()
