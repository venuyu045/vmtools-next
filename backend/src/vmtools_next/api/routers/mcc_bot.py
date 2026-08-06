"""MCC Bot management API routes."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from vmtools_next.api.deps import get_db, get_current_user
from vmtools_next.data.models.auth import UserModel
from vmtools_next.api.schemas.mcc import (
    MccBotCreate, MccBotResponse, MccBotConnectRequest,
    InventorySnapshot, InventorySlot, InventoryActionRequest,
    InventorySelectHotbarRequest, InventoryDropRequest,
    MccBotStatusList, MccBotStatusItem,
)
from vmtools_next.data.models.logistics import MccBotModel
from vmtools_next.adapters.mcc.mcc_mcp_client import MccMcpError

router = APIRouter(prefix="/api/mcc-bots", tags=["mcc-bots"])


def _scoped_bot_query(db: Session, user: UserModel):
    """Bot query — organization isolation removed (all data visible)."""
    return db.query(MccBotModel)


def _get_scoped_bot(db: Session, user: UserModel, bot_id: str) -> MccBotModel:
    """Fetch a bot visible to the user, 404 when missing or out of scope."""
    bot = _scoped_bot_query(db, user).filter(MccBotModel.bot_id == bot_id).first()
    if not bot:
        raise HTTPException(404, "Bot not found")
    return bot


@router.get("", response_model=list[MccBotResponse])
def list_bots(db: Session = Depends(get_db), user=Depends(get_current_user)):
    """List MCC bots visible to the user (same org, site_admin sees all)."""
    bots = _scoped_bot_query(db, user).all()
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


# ── MCC 状态概览（只读，与 MCC 管理页隔离） ─────────────────────

def _load_residences():
    """复用 BluemapMonitor 缓存的领地数据（含中心坐标），失败时回退 DB 缓存。"""
    try:
        from vmtools_next.main import get_bluemap_monitor
        monitor = get_bluemap_monitor()
        if monitor:
            rs = monitor.get_residences()
            if rs:
                return rs
    except Exception:
        pass
    try:
        import json as _json
        from vmtools_next.data.db import get_session_factory
        from sqlalchemy import text
        with get_session_factory()() as db:
            row = db.execute(
                text("SELECT cache_data FROM bluemap_cache WHERE cache_key = 'bluemap_residences'"),
            ).fetchone()
            if row and row[0]:
                return _json.loads(row[0])
    except Exception:
        pass
    return []


def _nearest_residence(loc: dict, residences: list[dict]):
    """计算 bot 坐标最近的领地（水平距离，欧氏）。"""
    bx, bz = loc.get("x"), loc.get("z")
    if bx is None or bz is None or not residences:
        return None
    best, best_d2 = None, float("inf")
    for r in residences:
        p = r.get("position") or {}
        rx, rz = p.get("x"), p.get("z")
        if rx is None or rz is None:
            continue
        d2 = (bx - rx) ** 2 + (bz - rz) ** 2
        if d2 < best_d2:
            best_d2 = d2
            best = r
    if best is None:
        return None
    import math
    return {
        "label": best.get("label", ""),
        "owner": best.get("owner", ""),
        "world": best.get("world", ""),
        "distance": round(math.sqrt(best_d2), 1),
        "position": best.get("position", {}),
    }


def _get_bot_current_task(db: Session, bot_id: str):
    """查 bot 当前进行中的工作：物流 > 地图画 > 仓库扫描。无则 None（空闲）。"""
    # 1) 物流运行（logistics_task_runs）
    from vmtools_next.data.models.logistics import LogisticsTaskRunModel, LogisticsTaskTemplateModel
    run = db.query(LogisticsTaskRunModel).filter(
        LogisticsTaskRunModel.bot_id == bot_id,
        LogisticsTaskRunModel.status.in_(["running", "paused"]),
    ).order_by(LogisticsTaskRunModel.started_at.desc()).first()
    if run:
        tpl_name = run.template_id
        tpl = db.query(LogisticsTaskTemplateModel).filter(
            LogisticsTaskTemplateModel.template_id == run.template_id
        ).first()
        if tpl:
            tpl_name = getattr(tpl, "name", None) or tpl_name
        return {"type": "logistics", "name": f"物流·{tpl_name}",
                "status": run.status, "progress": run.progress}

    # 2) 地图画（map_art_bot_assignments + map_art_tasks）
    from vmtools_next.data.models.build_map_art import MapArtBotAssignment, MapArtTask
    assign = db.query(MapArtBotAssignment).filter(
        MapArtBotAssignment.bot_id == bot_id,
    ).first()
    if assign:
        task = db.query(MapArtTask).filter(
            MapArtTask.task_id == assign.task_id,
            MapArtTask.status == "running",
        ).first()
        if task:
            progress = None
            if assign.blocks_total:
                progress = round(assign.blocks_placed / assign.blocks_total * 100, 1)
            return {"type": "mapart", "name": f"地图画·{task.name}",
                    "status": "running", "progress": progress}

    # 3) 仓库扫描（scan_queue）
    from vmtools_next.data.models.warehouse import ScanQueueModel, WarehouseModel
    scan = db.query(ScanQueueModel).filter(
        ScanQueueModel.bot_id == bot_id,
        ScanQueueModel.status.in_(["running", "paused"]),
    ).first()
    if scan:
        wh_name = scan.warehouse_id
        wh = db.query(WarehouseModel).filter(
            WarehouseModel.warehouse_id == scan.warehouse_id
        ).first()
        if wh:
            wh_name = getattr(wh, "name", None) or wh_name
        return {"type": "scan", "name": f"仓库扫描·{wh_name}",
                "status": scan.status, "progress": scan.progress}

    return None


@router.get("/status/overview", response_model=MccBotStatusList)
def bot_status_overview(engine: str = "mcc",
                        db: Session = Depends(get_db), user=Depends(get_current_user)):
    """每个 bot 的实时状态：在线情况/血量/饱食度/坐标/最近领地/当前工作。

    ``engine``：'mcc' | 'mineflayer'（MCC 状态与 MF 状态共用同一接口）。
    """
    import json as _json

    bots = _scoped_bot_query(db, user).all()
    residences = _load_residences()

    from vmtools_next.main import get_pool_for_engine
    from vmtools_next.core.bot_engine import resolve_bot_engine
    from vmtools_next.data.models.mcc_remote import MccInstanceModel

    items: list[MccBotStatusItem] = []
    for b in bots:
        # 只展示指定引擎的 bot
        try:
            if resolve_bot_engine(b.bot_id, db) != engine:
                continue
        except Exception:
            pass
        # 解析坐标（MccSessionPool/MineflayerSessionPool 定期写入的 JSON）
        loc = None
        if b.current_location:
            try:
                loc = _json.loads(b.current_location)
            except Exception:
                loc = None

        # 实时在线情况：优先取会话池状态（online/error），否则用 DB status
        status = b.status or "offline"
        last_hb = None
        mcp_port = None
        try:
            pool = get_pool_for_engine(resolve_bot_engine(b.bot_id, db))
            if pool:
                st = pool.get_bot_status(b.bot_id)
                if st.get("status") in ("online", "error"):
                    status = st["status"]
                last_hb = st.get("last_heartbeat")
                mcp_port = st.get("port")
        except Exception:
            pass
        if mcp_port is None:
            inst = db.query(MccInstanceModel).filter(
                MccInstanceModel.bot_id == b.bot_id
            ).first()
            if inst:
                mcp_port = inst.mcp_port

        nearest = _nearest_residence(loc, residences) if loc else None

        items.append(MccBotStatusItem(
            bot_id=b.bot_id,
            name=b.name or b.bot_id,
            status=status,
            mc_username=b.mc_username,
            current_health=b.current_health,
            current_food=b.current_food,
            current_location=loc,
            mcp_port=mcp_port,
            last_heartbeat=last_hb,
            nearest_residence=nearest,
            current_task=_get_bot_current_task(db, b.bot_id),
        ))

    # 在线优先排序
    order = {"online": 0, "error": 1, "offline": 2, "starting": 1}
    items.sort(key=lambda x: order.get(x.status, 9))
    return MccBotStatusList(items=items, residences_total=len(residences))


@router.post("", response_model=MccBotResponse)
def create_bot(data: MccBotCreate, db: Session = Depends(get_db),
               user=Depends(get_current_user)):
    """Register a new MCC bot (always bound to the creator's organization)."""
    existing = db.query(MccBotModel).filter(MccBotModel.bot_id == data.bot_id).first()
    if existing:
        raise HTTPException(400, "Bot already exists")
    payload = data.model_dump()
    payload["organization_id"] = user.organization_id
    bot = MccBotModel(**payload)
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
    """Get a specific bot (scoped by organization)."""
    bot = _get_scoped_bot(db, user, bot_id)
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
    """Delete a bot (scoped by organization)."""
    bot = _get_scoped_bot(db, user, bot_id)
    db.delete(bot)
    db.commit()
    return {"status": "deleted"}


@router.post("/{bot_id}/connect")
async def connect_bot(bot_id: str, data: MccBotConnectRequest,
                      db: Session = Depends(get_db), user=Depends(get_current_user)):
    """Connect a bot to MCC MCP server (scoped by organization)."""
    bot = _get_scoped_bot(db, user, bot_id)

    # Get pool from app state (injected by lifespan)
    from vmtools_next.main import get_pool_for_engine
    from vmtools_next.core.bot_engine import resolve_bot_engine
    # Route to the engine pool matching this bot's instance engine.
    engine = resolve_bot_engine(bot_id, db)
    pool = get_pool_for_engine(engine)
    if not pool:
        raise HTTPException(500, "Pool not initialized")

    success = await pool.connect_bot(bot_id, data.host, data.port, data.auth_token)
    bot.status = "online" if success else "error"
    db.commit()

    return {"bot_id": bot_id, "status": bot.status, "connected": success}


@router.post("/{bot_id}/disconnect")
async def disconnect_bot(bot_id: str, db: Session = Depends(get_db),
                         user=Depends(get_current_user)):
    """Disconnect a bot (scoped by organization)."""
    _get_scoped_bot(db, user, bot_id)
    from vmtools_next.main import get_pool_for_engine
    from vmtools_next.core.bot_engine import resolve_bot_engine
    pool = get_pool_for_engine(resolve_bot_engine(bot_id, db))
    if pool:
        await pool.disconnect_bot(bot_id)

    bot = db.query(MccBotModel).filter(MccBotModel.bot_id == bot_id).first()
    if bot:
        bot.status = "offline"
        db.commit()

    return {"bot_id": bot_id, "status": "offline"}


# ── MCP connection cache (shared session for inventory actions) ──

import time as _time
_mcp_conn_cache: dict[str, tuple[float, object]] = {}  # bot_id → (last_used_ts, client)
_MCP_CACHE_TTL = 120  # seconds


async def _get_mcp_client(bot_id: str, mcp_port: int = 0):
    """Get bot agent client from the engine-appropriate session pool, cache, or create new."""
    from vmtools_next.main import get_pool_for_engine
    from vmtools_next.core.bot_engine import resolve_bot_engine
    from vmtools_next.data.db import get_session_factory

    # 1. Try the pool matching this bot's engine
    with get_session_factory()() as db:
        engine = resolve_bot_engine(bot_id, db)
    pool = get_pool_for_engine(engine)
    if pool:
        client = pool.get_client(bot_id)
        if client:
            return client, False

    # 2. Try cache
    cached = _mcp_conn_cache.get(bot_id)
    if cached:
        ts, client = cached
        if _time.time() - ts < _MCP_CACHE_TTL:
            _mcp_conn_cache[bot_id] = (_time.time(), client)
            return client, True
        # Expired — clean up
        try: await client.disconnect()
        except: pass
        del _mcp_conn_cache[bot_id]

    # 3. Create new connection (MCC MCP fallback)
    port = mcp_port
    if not port:
        from vmtools_next.data.models.mcc_remote import MccInstanceModel
        with get_session_factory()() as db:
            inst = db.query(MccInstanceModel).filter(
                MccInstanceModel.bot_id == bot_id
            ).first()
            if inst:
                port = inst.mcp_port
    if not port:
        port = 33333

    from vmtools_next.adapters.mcc.mcc_mcp_client import MccMcpClient
    client = MccMcpClient(host="127.0.0.1", port=port, timeout_read=10)
    ok = await client.connect()
    if not ok:
        raise HTTPException(503, f"无法连接 MCC MCP port={port}")
    _mcp_conn_cache[bot_id] = (_time.time(), client)
    return client, True


@router.get("/{bot_id}/inventory")
async def get_inventory(bot_id: str, mcp_port: int = 0,
                        db: Session = Depends(get_db), user=Depends(get_current_user)):
    """Get bot's player inventory snapshot (scoped by organization)."""
    _get_scoped_bot(db, user, bot_id)
    client, owned = await _get_mcp_client(bot_id, mcp_port)
    try:
        snap = await client.get_inventory_snapshot(inventory_id=0)
        data = snap.get("data", snap)
        if not isinstance(data, dict):
            data = {"items": []}
    except MccMcpError as e:
        raise HTTPException(502, f"MCP error: {str(e) or repr(e)}")
    finally:
        pass  # keep connection alive in cache

    all_items = data.get("slots", data.get("items", [])) or []
    slot_count = data.get("slotCount", 46)
    parsed = []
    for s in all_items:
        item_id = (s.get("type") or s.get("itemId") or "").strip()
        if item_id:
            parsed.append(InventorySlot(
                slot=s.get("slot", 0),
                item_id=item_id,
                display_name=s.get("displayName", "") or item_id,
                count=s.get("count", s.get("amount", 0)) or 0,
                max_stack=s.get("maxStackSize", 64),
            ))

    return InventorySnapshot(
        bot_id=bot_id,
        inventory_id=data.get("id", 0),
        slots=parsed,
        hotbar=list(range(0, 9)),
        selected_hotbar=data.get("selectedHotbar", 0) or 0,
        empty_slots=slot_count - len(all_items),
        total_items=sum(s.get("count", s.get("amount", 0)) or 0 for s in all_items),
    )


@router.post("/{bot_id}/inventory/action")
async def inventory_action(bot_id: str, data: InventoryActionRequest,
                           db: Session = Depends(get_db), user=Depends(get_current_user)):
    """Perform a slot action (scoped by organization)."""
    _get_scoped_bot(db, user, bot_id)
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
        pass  # keep connection alive in cache


@router.post("/{bot_id}/inventory/drop")
async def inventory_drop(bot_id: str, data: InventoryDropRequest,
                         db: Session = Depends(get_db), user=Depends(get_current_user)):
    """Drop items from inventory by type (scoped by organization)."""
    _get_scoped_bot(db, user, bot_id)
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
        pass  # keep connection alive in cache


@router.post("/{bot_id}/inventory/select-hotbar")
async def inventory_select_hotbar(bot_id: str, data: InventorySelectHotbarRequest,
                                  db: Session = Depends(get_db), user=Depends(get_current_user)):
    """Select a hotbar slot (0-8) (scoped by organization)."""
    _get_scoped_bot(db, user, bot_id)
    client, owned = await _get_mcp_client(bot_id)
    try:
        result = await client.change_hotbar_slot(data.slot)
        return {"success": True, "slot": data.slot, "result": result}
    except MccMcpError as e:
        raise HTTPException(502, f"MCP error: {str(e) or repr(e)}")
    finally:
        if owned: await client.disconnect()
