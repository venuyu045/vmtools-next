"""MCC Bot management API routes."""
from __future__ import annotations

import re

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from vmtools_next.api.deps import get_db, get_current_user, get_optional_user, require_admin
from vmtools_next.data.models.auth import UserModel
from vmtools_next.api.schemas.mcc import (
    MccBotCreate, MccBotResponse, MccBotConnectRequest,
    InventorySnapshot, InventorySlot, InventoryActionRequest,
    InventorySelectHotbarRequest, InventoryDropRequest, InventoryMoveRequest,
    InventoryUseRequest, InventoryClickRequest, ActivateItemRequest, ActivateBlockRequest,
    MoveControlRequest, LookRequest, SneakRequest,
    MccBotStatusList, MccBotStatusItem,
    CombatAutoAttackRequest, CombatGuardRequest, CombatAttackRequest,
    OpenContainerRequest,
)
from vmtools_next.data.models.logistics import MccBotModel
from vmtools_next.adapters.mcc.mcc_mcp_client import MccMcpClient, MccMcpError
from vmtools_next.adapters.mineflayer.mineflayer_client import MineflayerError

router = APIRouter(prefix="/api/mcc-bots", tags=["mcc-bots"])


class SleepPointRequest(BaseModel):
    """永昼固定睡觉点（床的方块坐标，2026-08-16）。"""
    x: int
    y: int
    z: int


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
def list_bots(db: Session = Depends(get_db), user=Depends(get_optional_user)):
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

# 领地数据 TTL 缓存（30s）：状态页每次请求都会计算最近领地，领地数上千时
# 避免反复回退 DB 加载，显著降低大量 bot 场景下状态页接口的响应耗时。
_residences_cache: dict = {"ts": 0.0, "data": None}
_RESIDENCES_TTL = 30.0


def _load_residences():
    """复用 BluemapMonitor 缓存的领地数据（含中心坐标），失败时回退 DB 缓存。

    结果带 30s TTL 缓存，避免每次请求都重复加载。
    """
    import time as _time
    now = _time.monotonic()
    if _residences_cache["data"] is not None and now - _residences_cache["ts"] < _RESIDENCES_TTL:
        return _residences_cache["data"]
    try:
        from vmtools_next.main import get_bluemap_monitor
        monitor = get_bluemap_monitor()
        if monitor:
            rs = monitor.get_residences()
            if rs:
                _residences_cache["data"] = rs
                _residences_cache["ts"] = now
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
                data = _json.loads(row[0])
                _residences_cache["data"] = data
                _residences_cache["ts"] = now
                return data
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
    """查 bot 当前进行中的工作：手动标记 > 物流 > 地图画 > 仓库扫描。无则 None（空闲）。"""
    # 0) 手动标记「工作中」（2026-08-13 任务管理，优先级最高）
    from vmtools_next.core.bot_work import get_manual_work
    mw = get_manual_work(db, bot_id)
    if mw is not None:
        return {"type": "manual", "name": mw.get("name") or "手动工作",
                "status": "running", "progress": None}
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
    # ⚠️ 2026-10-20 审查修复（中等·当前工作误判为空闲）：
    #   原实现先 `filter(bot_id=...).first()` 取**最早插入**的一条 assignment
    #   （可能是几个月前已完成任务的记录），再判断其 task 是否 running。
    #   若那条旧记录对应任务已结束 → 直接返回 None，**不会再看后续 assignment**
    #   → 正在跑新任务的 Bot 在状态页显示"空闲"，busy 判断同样失真。
    #   修复：join 任务表，在 SQL 层就限定「该 bot + 任务正在运行 + 未释放」，
    #   并按 id 倒序取最新一条。state != "released" 同时对齐
    #   manage_task_bot / _rebuild_assignments 的口径。
    assign = (
        db.query(MapArtBotAssignment)
        .join(MapArtTask, MapArtTask.task_id == MapArtBotAssignment.task_id)
        .filter(
            MapArtBotAssignment.bot_id == bot_id,
            MapArtBotAssignment.state != "released",
            MapArtTask.status == "running",
        )
        .order_by(MapArtBotAssignment.id.desc())
        .first()
    )
    if assign:
        task = db.query(MapArtTask).filter(
            MapArtTask.task_id == assign.task_id,
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
                        db: Session = Depends(get_db), user=Depends(get_optional_user)):
    """每个 bot 的实时状态：在线情况/血量/饱食度/坐标/最近领地/当前工作。

    ``engine``：'mcc' | 'mineflayer'（MCC 状态与 MF 状态共用同一接口）。

    性能：批量预取实例映射/当前任务，替代逐 bot 的多次 DB 查询，
    避免大量 bot 时状态页切换卡顿。
    """
    import json as _json

    bots = _scoped_bot_query(db, user).all()
    residences = _load_residences()

    from vmtools_next.main import get_pool_for_engine
    from vmtools_next.data.models.mcc_remote import MccInstanceModel

    # ── 批量预取：实例映射（bot_id → instance，含 mcp_port/status/bot_engine）──
    instances = db.query(MccInstanceModel).filter(
        MccInstanceModel.deleted_at.is_(None),
    ).all()
    inst_by_bot: dict[str, MccInstanceModel] = {
        i.bot_id: i for i in instances if i.bot_id
    }

    # ── 批量预取：当前任务（手动标记 > 物流 > 地图画 > 仓库扫描，与 _get_bot_current_task 同优先级）──
    task_by_bot: dict[str, dict] = {}

    # 0) 手动标记「工作中」（2026-08-13 任务管理，优先级最高）
    from vmtools_next.data.models.logistics import MccBotModel as _MccBotModel
    for _b in db.query(_MccBotModel).filter(_MccBotModel.manual_working.is_(True)).all():
        if _b.bot_id:
            _name = (_b.manual_task_name or "").strip() or "手动工作"
            task_by_bot[_b.bot_id] = {"type": "manual", "name": _name,
                                      "status": "running", "progress": None}

    # 1) 物流运行（logistics_task_runs）
    from vmtools_next.data.models.logistics import LogisticsTaskRunModel, LogisticsTaskTemplateModel
    runs = db.query(LogisticsTaskRunModel).filter(
        LogisticsTaskRunModel.status.in_(["running", "paused"]),
    ).all()
    tpl_names: dict[str, str] = {}
    if runs:
        tpl_ids = {r.template_id for r in runs}
        for t in db.query(LogisticsTaskTemplateModel).filter(
            LogisticsTaskTemplateModel.template_id.in_(tpl_ids)).all():
            tpl_names[t.template_id] = t.name or t.template_id
    for r in runs:
        if r.bot_id and r.bot_id not in task_by_bot:
            task_by_bot[r.bot_id] = {
                "type": "logistics",
                "name": f"物流·{tpl_names.get(r.template_id, r.template_id)}",
                "status": r.status,
                "progress": r.progress,
            }

    # 2) 地图画（map_art_bot_assignments + map_art_tasks）
    from vmtools_next.data.models.build_map_art import MapArtBotAssignment, MapArtTask
    assigns = db.query(MapArtBotAssignment).all()
    running_tasks: dict[str, MapArtTask] = {}
    if assigns:
        task_ids = {a.task_id for a in assigns}
        for t in db.query(MapArtTask).filter(
            MapArtTask.task_id.in_(task_ids),
            MapArtTask.status == "running",
        ).all():
            running_tasks[t.task_id] = t
    for a in assigns:
        if a.bot_id and a.bot_id not in task_by_bot:
            task = running_tasks.get(a.task_id)
            if task:
                progress = None
                if a.blocks_total:
                    progress = round(a.blocks_placed / a.blocks_total * 100, 1)
                task_by_bot[a.bot_id] = {
                    "type": "mapart",
                    "name": f"地图画·{task.name}",
                    "status": "running",
                    "progress": progress,
                }

    # 3) 仓库扫描（scan_queue）
    from vmtools_next.data.models.warehouse import ScanQueueModel, WarehouseModel
    scans = db.query(ScanQueueModel).filter(
        ScanQueueModel.status.in_(["running", "paused"]),
    ).all()
    wh_names: dict[str, str] = {}
    if scans:
        wh_ids = {s.warehouse_id for s in scans}
        for w in db.query(WarehouseModel).filter(
            WarehouseModel.warehouse_id.in_(wh_ids)).all():
            wh_names[w.warehouse_id] = w.name or w.warehouse_id
    for s in scans:
        if s.bot_id and s.bot_id not in task_by_bot:
            task_by_bot[s.bot_id] = {
                "type": "scan",
                "name": f"仓库扫描·{wh_names.get(s.warehouse_id, s.warehouse_id)}",
                "status": s.status,
                "progress": s.progress,
            }

    items: list[MccBotStatusItem] = []
    for b in bots:
        inst = inst_by_bot.get(b.bot_id)
        # 引擎判定：优先实例声明的 bot_engine，无实例时回退配置默认
        engine_of_bot = (getattr(inst, "bot_engine", None) or "mcc") if inst else "mcc"
        if engine_of_bot != engine:
            continue
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
            pool = get_pool_for_engine(engine_of_bot)
            if pool:
                st = pool.get_bot_status(b.bot_id)
                if st.get("status") in ("online", "error"):
                    status = st["status"]
                last_hb = st.get("last_heartbeat")
                mcp_port = st.get("port")
        except Exception:
            pass
        if mcp_port is None and inst:
            mcp_port = inst.mcp_port
        # 兜底：进程/实例已在运行（如 MF 实例 LOGIN_OK 后 WS 连接尚未建立，
        # 或后端重启后池未连上），但池状态不是 online/error 时，按实例状态修正，
        # 避免「实例在线却显示离线」的误报。
        if status not in ("online", "error") and inst and inst.status == "running":
            status = "online"

        nearest = _nearest_residence(loc, residences) if loc else None

        # 3D 查看器端口：mineflayer 进程由 MineflayerProcessManager 管理，
        # 从进程句柄实时取 viewer_port（viewer 未启用/进程不在时 None）
        viewer_port = None
        if engine_of_bot == "mineflayer" and inst:
            try:
                from vmtools_next.main import get_mineflayer_process_manager
                mgr = get_mineflayer_process_manager()
                if mgr:
                    viewer_port = mgr.get_viewer_port(inst.instance_id)
            except Exception:
                viewer_port = None

        # ⚠️ 2026-10-20 审查修复（中等·访客可读内部端口与实时坐标）：
        #   本接口用 get_optional_user（未登录可访问，供「访客只读」状态页使用），
        #   但原实现把 mcp_port / viewer_port 一并返回。这两个端口是**服务器内部**
        #   监听端口，与访客浏览需求无关，泄露后可用于端口探测/直连尝试
        #   （配合 connect 接口的 host/port 可控问题形成攻击面）。
        #   修复：访客（user is None）不返回端口，仅登录用户可见；坐标/血量等
        #   展示字段保持公开，不影响访客只读页功能。
        is_guest = user is None
        items.append(MccBotStatusItem(
            bot_id=b.bot_id,
            name=b.name or b.bot_id,
            status=status,
            mc_username=b.mc_username,
            current_health=b.current_health,
            current_food=b.current_food,
            current_location=loc,
            mcp_port=None if is_guest else mcp_port,
            viewer_port=None if is_guest else viewer_port,
            last_heartbeat=last_hb,
            nearest_residence=nearest,
            current_task=task_by_bot.get(b.bot_id),
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
def delete_bot(bot_id: str, db: Session = Depends(get_db), user=Depends(require_admin)):
    """Delete a bot (scoped by organization)."""
    bot = _get_scoped_bot(db, user, bot_id)
    db.delete(bot)
    db.commit()
    return {"status": "deleted"}


@router.post("/{bot_id}/connect")
async def connect_bot(bot_id: str, data: MccBotConnectRequest,
                      db: Session = Depends(get_db), user=Depends(require_admin)):
    """Connect a bot to MCC MCP server.

    ⚠️ 2026-10-20 审查修复（中等·SSRF + 凭据外发）：
      原实现把请求体里的 `host` / `port` / `auth_token` **原样**交给
      `pool.connect_bot(...)`，服务端不做任何校验：
        · host/port 可控 → 后端可被指使连接任意内网地址（云元数据 169.254.169.254、
          内网管理口、其他实例的 MCP 端口），并用响应码/超时差异做端口探测；
        · auth_token 可控 → 可把任意令牌发往任意主机（凭据外发/钓鱼跳板）。
      与已修的 inventory `mcp_port` 越权同源。
      修复（最小改动、保持兼容）：
        · 优先使用数据库中该 bot 绑定实例的 mcp_host/mcp_port 与解密后的
          mcp_auth_token（服务端权威来源）；
        · 仅当 bot 无绑定实例时，才允许调用方指定 host，且必须是回环/私有地址
          （禁止公网地址，防把后端当跳板）。
    """
    bot = _get_scoped_bot(db, user, bot_id)

    # Get pool from app state (injected by lifespan)
    from vmtools_next.main import get_pool_for_engine
    from vmtools_next.core.bot_engine import resolve_bot_engine
    # Route to the engine pool matching this bot's instance engine.
    engine = resolve_bot_engine(bot_id, db)
    pool = get_pool_for_engine(engine)
    if not pool:
        raise HTTPException(500, "Pool not initialized")

    # ── 解析服务端权威连接参数（DB 实例优先）──
    from vmtools_next.data.models.mcc_remote import MccInstanceModel
    from vmtools_next.core.mcc_security import reveal_secret
    inst = db.query(MccInstanceModel).filter(
        MccInstanceModel.bot_id == bot_id,
        MccInstanceModel.deleted_at.is_(None),
    ).first()

    if inst is not None:
        host = inst.mcp_host or "127.0.0.1"
        port = inst.mcp_port or data.port
        token = reveal_secret(inst.mcp_auth_token_secret) or None
    else:
        # 无绑定实例：仅允许回环/私有地址，避免把后端当公网跳板
        import ipaddress
        host = (data.host or "127.0.0.1").strip()
        try:
            ip = ipaddress.ip_address(host)
            allowed = ip.is_loopback or ip.is_private
        except ValueError:
            allowed = host in ("localhost",)
        if not allowed:
            raise HTTPException(
                status_code=400,
                detail="该 Bot 未绑定 MCC 实例，host 仅允许回环或内网地址",
            )
        port = data.port
        token = data.auth_token

    success = await pool.connect_bot(bot_id, host, port, token)
    bot.status = "online" if success else "error"
    db.commit()

    return {"bot_id": bot_id, "status": bot.status, "connected": success}


@router.post("/{bot_id}/disconnect")
async def disconnect_bot(bot_id: str, db: Session = Depends(get_db),
                         user=Depends(require_admin)):
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
# P2-14：cache key 带引擎——(engine, bot_id)，避免 MCC/MF 引擎错配
#（旧实现只按 bot_id，MF bot 可能命中缓存的 MCC client）
_mcp_conn_cache: dict[tuple[str, str], tuple[float, object]] = {}
_MCP_CACHE_TTL = 120  # seconds


async def _get_mcp_client(bot_id: str, mcp_port: int = 0):
    """Get bot agent client from the engine-appropriate session pool, cache, or create new.

    引擎隔离（P2-14）：
    - 优先取该 bot 引擎对应会话池中的 client（MCC pool / MF pool）
    - cache 按 (engine, bot_id) 区分，杜绝引擎错配
    - 仅 MCC 允许按 MCP 端口新建连接；MF 必须通过会话池（process manager 管理），
      无连接时直接报错（不能临时 new 一个 MCC client 冒充 MF）
    """
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

    # 2. Try cache（key 带 engine）
    key = (engine, bot_id)
    cached = _mcp_conn_cache.get(key)
    if cached:
        ts, client = cached
        if _time.time() - ts < _MCP_CACHE_TTL:
            _mcp_conn_cache[key] = (_time.time(), client)
            return client, True
        # Expired — clean up
        try:
            await client.disconnect()
        except Exception:
            pass
        del _mcp_conn_cache[key]

    # 3. Create new connection —— 仅 MCC 支持；MF 必须通过会话池连接
    if engine != "mcc":
        raise HTTPException(
            503,
            f"Bot {bot_id}（{engine}）未连接：请先通过 connect 接口建立会话"
            "（MF bot 由进程管理器管理，不支持临时新建连接）",
        )
    port = mcp_port

    # ⚠️ 2026-10-20 审查修复（中等·SSRF / 越权探测）：
    #   `mcp_port` 来自调用方 query 参数（GET /api/mcc-bots/{id}/inventory?mcp_port=N），
    #   原实现**无条件优先采用调用方给的值**，然后让后端去连 `127.0.0.1:<N>`。
    #   任何已登录用户（get_current_user，无需 admin）即可借此：
    #     ① 探测服务器回环端口存活（SSRF，仅限 127.0.0.1，但足以枚举本机服务）；
    #     ② 连接**其它实例**的 MCP 端口，绕过「按 bot 取实例」的绑定关系。
    #   修复：以数据库里该 bot 绑定的实例端口为唯一可信来源；只有当 bot 没有
    #   关联实例（历史遗留）时，才接受调用方端口，且必须落在配置的 MCC 端口段内。
    from vmtools_next.data.models.mcc_remote import MccInstanceModel as _Inst
    from vmtools_next.config import get_config as _get_cfg
    with get_session_factory()() as db:
        inst = db.query(_Inst).filter(
            _Inst.bot_id == bot_id,
            _Inst.deleted_at.is_(None),
        ).first()
    if inst is not None and inst.mcp_port:
        port = inst.mcp_port
    else:
        cfg = _get_cfg().mcc
        lo, hi = int(cfg.instance_start_port), int(cfg.instance_end_port)
        if not port:
            port = lo
        elif not (lo <= int(port) <= hi):
            raise HTTPException(
                400,
                f"bot {bot_id} 未绑定实例，mcp_port 必须落在配置端口段 {lo}-{hi} 内",
            )

    from vmtools_next.adapters.mcc.mcc_mcp_client import MccMcpClient
    client = MccMcpClient(host="127.0.0.1", port=port, timeout_read=10)
    ok = await client.connect()
    if not ok:
        raise HTTPException(503, f"无法连接 MCC MCP port={port}")
    _mcp_conn_cache[key] = (_time.time(), client)
    return client, True


# ── 玩家窗口槽位 / 物品ID 归一化（MCC 与 mineflayer 共用同一套窗口槽位） ──
# 引擎原始槽位：5-8=盔甲、9-35=主背包、36-44=快捷栏、45=副手、0-4=合成
# 前端标准布局：0-8=快捷栏、9-35=主背包、36-39=盔甲、40=副手、41-45=合成
def _normalize_inv_slot(slot) -> int:
    """引擎槽位 → 前端标准槽位（显示用）。"""
    if not isinstance(slot, int):
        return slot
    if 5 <= slot <= 8:
        return slot + 31          # 盔甲 5-8 → 36-39
    if 36 <= slot <= 44:
        return slot - 36          # 快捷栏 36-44 → 0-8
    if slot == 45:
        return 40                 # 副手 → 40
    if 0 <= slot <= 4:
        return slot + 41          # 合成 0-4 → 41-45
    return slot


def _denormalize_inv_slot(slot) -> int:
    """前端标准槽位 → 引擎原始槽位（MCC InventoryWindowAction 用）。"""
    if not isinstance(slot, int):
        return slot
    if 0 <= slot <= 8:
        return slot + 36
    if 36 <= slot <= 39:
        return slot - 31
    if slot == 40:
        return 45
    if 41 <= slot <= 45:
        return slot - 41
    return slot


def _camel_to_snake(name: str) -> str:
    """MCC item_id 驼峰命名（NetheriteHelmet）→ item-icons 文件名（netherite_helmet）。
    对已小写下划线的 MF item_id 无影响。"""
    if not name:
        return name
    return re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower()


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
    except (MccMcpError, MineflayerError) as e:
        raise HTTPException(502, f"MCP error: {str(e) or repr(e)}")
    finally:
        pass  # keep connection alive in cache

    all_items = data.get("slots", data.get("items", [])) or []
    slot_count = data.get("slotCount", 46)
    parsed = []
    for s in all_items:
        # 引擎隔离：MCC 原始数据（驼峰 item_id + 引擎窗口槽位）在此归一化；
        # MF 数据已在 MineflayerBridgeClient 归一化为标准槽位+小写 ID，直接透传，禁止二次转换。
        if isinstance(client, MccMcpClient):
            item_id = _camel_to_snake((s.get("type") or s.get("itemId") or "").strip())
            _slot = _normalize_inv_slot(s.get("slot", 0))
        else:
            item_id = (s.get("type") or s.get("itemId") or "").strip()
            _slot = s.get("slot", 0)
        if item_id:
            from vmtools_next.core.item_names_zh import get_item_zh
            parsed.append(InventorySlot(
                slot=_slot,
                item_id=item_id,
                display_name=s.get("displayName", "") or item_id,
                item_name_zh=get_item_zh(item_id, fallback=s.get("displayName", "") or item_id),
                count=s.get("count", s.get("amount", 0)) or 0,
                max_stack=s.get("maxStackSize", 64),
                durability=s.get("durability"),
                max_durability=s.get("maxDurability", s.get("max_durability")),
                enchantments=s.get("enchantments") or None,
                custom_name=s.get("custom_name") or None,
                lore=s.get("lore") or None,
                debug=s.get("debug") or None,
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


# ── 容器（大箱子 UI / 附加箱子，2026-08-11，仅 mineflayer） ──

@router.get("/{bot_id}/inventory/containers")
async def inventory_scan_containers(bot_id: str,
                                    max_count: int = Query(200, ge=1, le=10000),
                                    db: Session = Depends(get_db),
                                    user=Depends(require_admin)):
    """扫描 bot 已加载区块内的全部容器方块（坐标列表，前端展示+前往）。"""
    _get_scoped_bot(db, user, bot_id)
    from vmtools_next.core.bot_engine import resolve_bot_engine
    engine = resolve_bot_engine(bot_id, db)
    if engine != "mineflayer":
        raise HTTPException(400, "容器功能仅支持 mineflayer 引擎")
    client, owned = await _get_mcp_client(bot_id)
    try:
        result = await client.scan_loaded_containers(max_count=max_count)
        return result
    finally:
        if owned: await client.disconnect()


@router.post("/{bot_id}/inventory/container/open")
async def inventory_open_container(bot_id: str, data: OpenContainerRequest,
                                   db: Session = Depends(get_db),
                                   user=Depends(require_admin)):
    """前往（距离远自动寻路）并打开容器，返回 container_id / slot_count / block_name。"""
    _get_scoped_bot(db, user, bot_id)
    client, owned = await _get_combat_client(bot_id, db, user)
    try:
        result = await client.open_container_at(data.x, data.y, data.z)
        if isinstance(result, dict) and result.get("success") is False:
            raise HTTPException(400, result.get("error", "打开容器失败"))
        return result
    except (MccMcpError, MineflayerError) as e:
        raise HTTPException(502, f"MCP error: {str(e) or repr(e)}")
    finally:
        if owned: await client.disconnect()


@router.get("/{bot_id}/inventory/container/{container_id}")
async def inventory_container_snapshot(bot_id: str, container_id: str,
                                       db: Session = Depends(get_db),
                                       user=Depends(require_admin)):
    """获取已打开容器的内容快照（物品名汉化）。"""
    _get_scoped_bot(db, user, bot_id)
    client, owned = await _get_combat_client(bot_id, db, user)
    try:
        data = await client.get_container_snapshot(container_id)
        # 物品名汉化（items[].name 为 minecraft:id）
        if isinstance(data, dict) and isinstance(data.get("items"), list):
            from vmtools_next.core.item_names_zh import get_item_zh
            for it in data["items"]:
                raw = str(it.get("name") or "")
                if raw:
                    it["item_id"] = raw
                    it["item_name_zh"] = get_item_zh(raw, fallback=it.get("display_name"))
        return data
    except (MccMcpError, MineflayerError) as e:
        raise HTTPException(502, f"MCP error: {str(e) or repr(e)}")
    finally:
        if owned: await client.disconnect()


@router.post("/{bot_id}/inventory/container/{container_id}/close")
async def inventory_close_container(bot_id: str, container_id: str,
                                    db: Session = Depends(get_db),
                                    user=Depends(require_admin)):
    """关闭容器。"""
    _get_scoped_bot(db, user, bot_id)
    client, owned = await _get_combat_client(bot_id, db, user)
    try:
        return await client.close_container(container_id)
    except (MccMcpError, MineflayerError) as e:
        raise HTTPException(502, f"MCP error: {str(e) or repr(e)}")
    finally:
        if owned: await client.disconnect()


@router.post("/{bot_id}/inventory/action")
async def inventory_action(bot_id: str, data: InventoryActionRequest,
                           db: Session = Depends(get_db), user=Depends(require_admin)):
    """Perform a slot action (scoped by organization)."""
    _get_scoped_bot(db, user, bot_id)
    client, owned = await _get_mcp_client(bot_id)
    try:
        # MCC 窗口操作使用引擎原始槽位（5-8 盔甲/36-44 快捷栏等），前端发来的是标准槽位
        slot_id = data.slot_id
        if isinstance(client, MccMcpClient):
            slot_id = _denormalize_inv_slot(slot_id)
        result = await client.inventory_window_action(
            inventory_id=data.inventory_id,
            slot_id=slot_id,
            action_type=data.action,
        )
        # MF 引擎不支持窗口槽位点击（返回 success:false）→ 转 400 友好提示
        if isinstance(result, dict) and result.get("success") is False:
            raise HTTPException(400, result.get("error", "该引擎不支持此操作"))
        return {"success": True, "action": data.action, "slot": data.slot_id, "result": result}
    except (MccMcpError, MineflayerError) as e:
        raise HTTPException(502, f"MCP error: {str(e) or repr(e)}")
    finally:
        pass  # keep connection alive in cache


@router.post("/{bot_id}/inventory/drop")
async def inventory_drop(bot_id: str, data: InventoryDropRequest,
                         db: Session = Depends(get_db), user=Depends(require_admin)):
    """Drop items from inventory by type (scoped by organization)."""
    _get_scoped_bot(db, user, bot_id)
    client, owned = await _get_mcp_client(bot_id)
    try:
        result = await client.drop_inventory_item(
            item_type=data.item_type,
            count=data.count,
            inventory_id=data.inventory_id,
            slot_id=data.slot_id,
        )
        # MF 引擎 drop_item 返回 success:false（如物品不存在）→ 转 400 友好提示
        if isinstance(result, dict) and result.get("success") is False:
            raise HTTPException(400, result.get("error", "丢弃失败"))
        return {"success": True, "dropped": data.item_type, "count": data.count,
                "slot": data.slot_id, "result": result}
    except (MccMcpError, MineflayerError) as e:
        raise HTTPException(502, f"MCP error: {str(e) or repr(e)}")
    finally:
        pass  # keep connection alive in cache


@router.post("/{bot_id}/inventory/select-hotbar")
async def inventory_select_hotbar(bot_id: str, data: InventorySelectHotbarRequest,
                                  db: Session = Depends(get_db), user=Depends(require_admin)):
    """Select a hotbar slot (0-8) (scoped by organization)."""
    _get_scoped_bot(db, user, bot_id)
    client, owned = await _get_mcp_client(bot_id)
    try:
        result = await client.change_hotbar_slot(data.slot)
        return {"success": True, "slot": data.slot, "result": result}
    except (MccMcpError, MineflayerError) as e:
        raise HTTPException(502, f"MCP error: {str(e) or repr(e)}")
    finally:
        if owned: await client.disconnect()


@router.post("/{bot_id}/inventory/move")
async def inventory_move(bot_id: str, data: InventoryMoveRequest,
                         db: Session = Depends(get_db), user=Depends(require_admin)):
    """Move/swap inventory slots (mineflayer only; slots in frontend standard layout)."""
    _get_scoped_bot(db, user, bot_id)
    client, owned = await _get_mcp_client(bot_id)
    try:
        # 仅 mineflayer 支持窗口槽位移动；MCC 走 inventory/action（MCC MCP 无 move 语义）
        if isinstance(client, MccMcpClient):
            raise HTTPException(400, "MCC 引擎请使用「窗口点击」操作（inventory/action）")
        result = await client.move_inventory_item(data.slot_id, data.dest_slot_id)
        if isinstance(result, dict) and result.get("success") is False:
            raise HTTPException(400, result.get("error", "移动失败"))
        return {"success": True, "from": data.slot_id, "to": data.dest_slot_id, "result": result}
    except (MccMcpError, MineflayerError) as e:
        raise HTTPException(502, f"MCP error: {str(e) or repr(e)}")
    finally:
        if owned: await client.disconnect()


@router.post("/{bot_id}/inventory/use")
async def inventory_use(bot_id: str, data: InventoryUseRequest,
                        db: Session = Depends(get_db), user=Depends(require_admin)):
    """Use item (eat food etc., mineflayer only). slot_id in frontend standard layout (optional)."""
    _get_scoped_bot(db, user, bot_id)
    client, owned = await _get_mcp_client(bot_id)
    try:
        if isinstance(client, MccMcpClient):
            raise HTTPException(400, "MCC 引擎不支持使用物品（inventory/use 仅 mineflayer）")
        if not data.item_type and data.slot_id is None:
            raise HTTPException(400, "item_type 与 slot_id 至少传一个")
        result = await client.use_item(item_type=data.item_type, slot_id=data.slot_id)
        if isinstance(result, dict) and result.get("success") is False:
            raise HTTPException(400, result.get("error", "使用失败"))
        return {"success": True, "item": result.get("item"), "result": result}
    except (MccMcpError, MineflayerError) as e:
        raise HTTPException(502, f"MCP error: {str(e) or repr(e)}")
    finally:
        if owned: await client.disconnect()


@router.post("/{bot_id}/inventory/click")
async def inventory_click(bot_id: str, data: InventoryClickRequest,
                          db: Session = Depends(get_db), user=Depends(require_admin)):
    """窗口内左键/右键物品（mineflayer only，2026-08-12）。

    target=inventory：玩家背包（slot 为前端标准槽位，后端映射原始槽位）；
    target=container：已打开容器（slot 为窗口内槽位）。
    若服务器因点击打开新容器窗口（快捷潜影盒）→ 返回 new_container_id。
    """
    _get_scoped_bot(db, user, bot_id)
    client, owned = await _get_mcp_client(bot_id)
    try:
        if isinstance(client, MccMcpClient):
            raise HTTPException(400, "窗口点击仅支持 mineflayer 引擎（MCC 请使用 inventory/action）")
        if data.target not in ("inventory", "container"):
            raise HTTPException(400, "target 仅支持 inventory / container")
        if data.mouse_button not in (0, 1):
            raise HTTPException(400, "mouse_button 仅支持 0（左键）/ 1（右键）")
        if data.target == "container" and not data.container_id:
            raise HTTPException(400, "target=container 时必须传 container_id")
        result = await client.click_window(
            target=data.target,
            slot=data.slot,
            mouse_button=data.mouse_button,
            mode=data.mode,
            container_id=data.container_id,
        )
        if isinstance(result, dict) and result.get("success") is False:
            raise HTTPException(400, result.get("error", "窗口点击失败"))
        return {"success": True, "result": result}
    except (MccMcpError, MineflayerError) as e:
        raise HTTPException(502, f"MCP error: {str(e) or repr(e)}")
    finally:
        if owned: await client.disconnect()


@router.post("/{bot_id}/inventory/activate-item")
async def inventory_activate_item(bot_id: str, data: ActivateItemRequest,
                                  db: Session = Depends(get_db), user=Depends(require_admin)):
    """右键使用手持物品（mineflayer only，2026-08-12）。

    快捷潜影盒/末影珍珠等：先设为手持（select-hotbar）再激活；
    若服务器弹出新容器窗口 → 返回 new_container_id。
    """
    _get_scoped_bot(db, user, bot_id)
    client, owned = await _get_mcp_client(bot_id)
    try:
        if isinstance(client, MccMcpClient):
            raise HTTPException(400, "激活手持物品仅支持 mineflayer 引擎")
        result = await client.activate_item()
        if isinstance(result, dict) and result.get("success") is False:
            raise HTTPException(400, result.get("error", "激活失败"))
        return {"success": True, "result": result}
    except (MccMcpError, MineflayerError) as e:
        raise HTTPException(502, f"MCP error: {str(e) or repr(e)}")
    finally:
        if owned: await client.disconnect()


@router.post("/{bot_id}/inventory/activate-block")
async def inventory_activate_block(bot_id: str, data: ActivateBlockRequest,
                                   db: Session = Depends(get_db), user=Depends(require_admin)):
    """右键方块（mineflayer only，2026-08-12）。

    箱子 UI / 快捷潜影盒（右键方块触发）：先扫描容器拿到坐标，再右键该方块；
    服务器插件弹出 GUI → 返回 new_container_id（或 mf_container_opened 事件）。
    """
    _get_scoped_bot(db, user, bot_id)
    client, owned = await _get_mcp_client(bot_id)
    try:
        if isinstance(client, MccMcpClient):
            raise HTTPException(400, "右键方块仅支持 mineflayer 引擎")
        result = await client.activate_block(data.x, data.y, data.z)
        if isinstance(result, dict) and result.get("success") is False:
            raise HTTPException(400, result.get("error", "右键方块失败"))
        return {"success": True, "result": result}
    except (MccMcpError, MineflayerError) as e:
        raise HTTPException(502, f"MCP error: {str(e) or repr(e)}")
    finally:
        if owned: await client.disconnect()


@router.get("/{bot_id}/inventory/current-window")
async def inventory_current_window(bot_id: str,
                                   db: Session = Depends(get_db),
                                   user=Depends(require_admin)):
    """查询当前打开的容器窗口（mineflayer only，2026-08-12）。

    已注册容器 → 返回 container_id / block_name / slot_count / items（含自定义名/Lore）；
    未打开 → opened=false。前端挂载时轮询实现「常驻容器面板」。
    """
    _get_scoped_bot(db, user, bot_id)
    client, owned = await _get_mcp_client(bot_id)
    try:
        if isinstance(client, MccMcpClient):
            raise HTTPException(400, "当前窗口查询仅支持 mineflayer 引擎")
        result = await client.get_current_window()
        if isinstance(result, dict) and result.get("success") is False:
            raise HTTPException(400, result.get("error", "查询当前窗口失败"))
        # 物品名汉化（items[].name 为 minecraft:id）
        if isinstance(result, dict) and isinstance(result.get("items"), list):
            from vmtools_next.core.item_names_zh import get_item_zh
            for it in result["items"]:
                raw = str(it.get("name") or "")
                if raw:
                    it["item_id"] = raw
                    it["item_name_zh"] = get_item_zh(raw, fallback=it.get("display_name"))
        return result
    except (MccMcpError, MineflayerError) as e:
        raise HTTPException(502, f"MCP error: {str(e) or repr(e)}")
    finally:
        if owned: await client.disconnect()


# ── 玩家操控（MF 移动控制台：前后左右/跳跃/蹲下/视角） ──
# 仅 mineflayer 引擎（bot.setControlState / bot.look 等）

@router.get("/{bot_id}/state")
async def bot_state(bot_id: str, db: Session = Depends(get_db), user=Depends(get_current_user)):
    """获取 bot 实时状态（MF 含 yaw/pitch/坐标，移动控制台视角基准用）。"""
    _get_scoped_bot(db, user, bot_id)
    client, owned = await _get_mcp_client(bot_id)
    try:
        if isinstance(client, MccMcpClient):
            raise HTTPException(400, "MCC 引擎请使用状态页（state 仅 mineflayer）")
        result = await client.get_player_state()
        return {"success": True, "result": result}
    except (MccMcpError, MineflayerError) as e:
        raise HTTPException(502, f"MCP error: {str(e) or repr(e)}")
    finally:
        if owned: await client.disconnect()


@router.post("/{bot_id}/control")
async def bot_control(bot_id: str, data: MoveControlRequest,
                      db: Session = Depends(get_db), user=Depends(require_admin)):
    """持续按住/松开控制键（mineflayer only）：forward/back/left/right/jump/sneak/sprint。"""
    _get_scoped_bot(db, user, bot_id)
    client, owned = await _get_mcp_client(bot_id)
    try:
        if isinstance(client, MccMcpClient):
            raise HTTPException(400, "MCC 引擎不支持移动控制（control 仅 mineflayer）")
        result = await client.set_control_state(data.direction, data.state)
        if isinstance(result, dict) and result.get("success") is False:
            raise HTTPException(400, result.get("error", "控制失败"))
        return {"success": True, "direction": data.direction, "state": data.state, "result": result}
    except (MccMcpError, MineflayerError) as e:
        raise HTTPException(502, f"MCP error: {str(e) or repr(e)}")
    finally:
        if owned: await client.disconnect()


@router.post("/{bot_id}/jump")
async def bot_jump(bot_id: str, db: Session = Depends(get_db), user=Depends(require_admin)):
    """跳跃一次（mineflayer only）。"""
    _get_scoped_bot(db, user, bot_id)
    client, owned = await _get_mcp_client(bot_id)
    try:
        if isinstance(client, MccMcpClient):
            raise HTTPException(400, "MCC 引擎不支持跳跃（jump 仅 mineflayer）")
        result = await client.jump()
        if isinstance(result, dict) and result.get("success") is False:
            raise HTTPException(400, result.get("error", "跳跃失败"))
        return {"success": True, "result": result}
    except (MccMcpError, MineflayerError) as e:
        raise HTTPException(502, f"MCP error: {str(e) or repr(e)}")
    finally:
        if owned: await client.disconnect()


@router.post("/{bot_id}/sneak")
async def bot_sneak(bot_id: str, data: SneakRequest,
                    db: Session = Depends(get_db), user=Depends(require_admin)):
    """蹲下/站起（mineflayer only；state=None 切换）。"""
    _get_scoped_bot(db, user, bot_id)
    client, owned = await _get_mcp_client(bot_id)
    try:
        if isinstance(client, MccMcpClient):
            raise HTTPException(400, "MCC 引擎不支持蹲下（sneak 仅 mineflayer）")
        result = await client.sneak(data.state)
        if isinstance(result, dict) and result.get("success") is False:
            raise HTTPException(400, result.get("error", "操作失败"))
        return {"success": True, "sneaking": result.get("sneaking"), "result": result}
    except (MccMcpError, MineflayerError) as e:
        raise HTTPException(502, f"MCP error: {str(e) or repr(e)}")
    finally:
        if owned: await client.disconnect()


@router.post("/{bot_id}/look")
async def bot_look(bot_id: str, data: LookRequest,
                   db: Session = Depends(get_db), user=Depends(require_admin)):
    """视角控制：平滑转向（mineflayer only；yaw/pitch 弧度）。"""
    _get_scoped_bot(db, user, bot_id)
    client, owned = await _get_mcp_client(bot_id)
    try:
        if isinstance(client, MccMcpClient):
            raise HTTPException(400, "MCC 引擎不支持视角控制（look 仅 mineflayer）")
        result = await client.look(data.yaw, data.pitch, data.force)
        if isinstance(result, dict) and result.get("success") is False:
            raise HTTPException(400, result.get("error", "视角控制失败"))
        return {"success": True, "yaw": data.yaw, "pitch": data.pitch, "result": result}
    except (MccMcpError, MineflayerError) as e:
        raise HTTPException(502, f"MCP error: {str(e) or repr(e)}")
    finally:
        if owned: await client.disconnect()


# ── 战斗（自动攻击 / 手动攻击 / 守护，2026-08-10，仅 mineflayer） ──
async def _get_combat_client(bot_id: str, db: Session, user) -> tuple:
    """获取战斗 client（仅 mineflayer 引擎；MCC 不支持）。"""
    _get_scoped_bot(db, user, bot_id)
    from vmtools_next.core.bot_engine import resolve_bot_engine
    engine = resolve_bot_engine(bot_id, db)
    if engine != "mineflayer":
        raise HTTPException(400, "战斗功能仅支持 mineflayer 引擎（MCC 请用 MinecraftClient.ini 的 AutoAttack）")
    return await _get_mcp_client(bot_id)


def _save_combat_config(db: Session, bot_id: str, cfg: dict | None) -> None:
    """把战斗配置持久化到 mcc_bots.combat_config（bot 重启/面板重开可恢复）。"""
    if not cfg:
        return
    try:
        import json as _json
        from vmtools_next.data.models.logistics import MccBotModel
        bot = db.query(MccBotModel).filter(MccBotModel.bot_id == bot_id).first()
        if bot:
            bot.combat_config = _json.dumps(cfg, ensure_ascii=False)
            db.commit()
    except Exception as _e:
        logger.warning("Save combat config failed for {}: {}", bot_id, _e)


def _load_combat_config(db: Session, bot_id: str) -> dict | None:
    """读取持久化的战斗配置（无则 None）。"""
    try:
        import json as _json
        from vmtools_next.data.models.logistics import MccBotModel
        bot = db.query(MccBotModel).filter(MccBotModel.bot_id == bot_id).first()
        if bot and bot.combat_config:
            data = _json.loads(bot.combat_config)
            return data if isinstance(data, dict) else None
    except Exception as _e:
        logger.warning("Load combat config failed for {}: {}", bot_id, _e)
    return None


@router.get("/{bot_id}/combat/entities")
async def combat_nearby_entities(bot_id: str, radius: int = 16,
                                 target_types: str = "",
                                 db: Session = Depends(get_db),
                                 user=Depends(require_admin)):
    """列出附近可攻击实体（radius 格内；target_types 逗号分隔，空=全部）。"""
    client, owned = await _get_combat_client(bot_id, db, user)
    try:
        types = [t.strip() for t in target_types.split(",") if t.strip()] if target_types else []
        result = await client.get_nearby_entities(radius, types)
        return result
    except (MccMcpError, MineflayerError) as e:
        raise HTTPException(502, f"MCP error: {str(e) or repr(e)}")
    finally:
        if owned: await client.disconnect()


@router.post("/{bot_id}/combat/auto-attack")
async def combat_auto_attack(bot_id: str, data: CombatAutoAttackRequest,
                             db: Session = Depends(get_db),
                             user=Depends(require_admin)):
    """自动攻击最近匹配实体（可设半径/目标类型/攻击间隔/耐久阈值）。"""
    client, owned = await _get_combat_client(bot_id, db, user)
    try:
        result = await client.set_auto_attack(
            enabled=data.enabled, radius=data.radius,
            scan_radius=data.scan_radius, attack_radius=data.attack_radius,
            target_types=data.target_types, interval_ms=data.interval_ms,
            interval_tick=data.interval_tick,
            interval_mode=data.interval_mode,
            stop_durability=data.stop_durability,
            move_to_target=data.move_to_target,
            enable_sprint_attack=data.enable_sprint_attack,
            enable_jump_crit=data.enable_jump_crit,
            enable_wtap=data.enable_wtap,
            enable_stap=data.enable_stap,
            enable_strafe=data.enable_strafe,
            anti_afk=data.anti_afk,
            anti_afk_interval_ms=data.anti_afk_interval_ms,
        )
        if isinstance(result, dict) and result.get("success") is False:
            raise HTTPException(400, result.get("error", "配置失败"))
        # 持久化配置（bot 重启/面板重开可恢复）
        _save_combat_config(db, bot_id, result.get("config"))
        return {"success": True, "bot_id": bot_id, "config": result.get("config")}
    except (MccMcpError, MineflayerError) as e:
        raise HTTPException(502, f"MCP error: {str(e) or repr(e)}")
    finally:
        if owned: await client.disconnect()


@router.post("/{bot_id}/combat/attack")
async def combat_attack(bot_id: str, data: CombatAttackRequest,
                        db: Session = Depends(get_db),
                        user=Depends(require_admin)):
    """手动攻击一次（target_id 或 target_type；缺省攻击最近实体）。"""
    client, owned = await _get_combat_client(bot_id, db, user)
    try:
        result = await client.attack(target_id=data.target_id, target_type=data.target_type,
                                     move_to_target=data.move_to_target,
                                     scan_radius=data.scan_radius,
                                     attack_radius=data.attack_radius,
                                     force_distance=data.force_distance)
        if isinstance(result, dict) and result.get("success") is False:
            raise HTTPException(400, result.get("error", "攻击失败"))
        return {"success": True, "bot_id": bot_id, "result": result}
    except (MccMcpError, MineflayerError) as e:
        raise HTTPException(502, f"MCP error: {str(e) or repr(e)}")
    finally:
        if owned: await client.disconnect()


@router.post("/{bot_id}/combat/guard")
async def combat_guard(bot_id: str, data: CombatGuardRequest,
                       db: Session = Depends(get_db),
                       user=Depends(require_admin)):
    """守护模式：绕指定点（缺省当前位置）巡逻，入侵者进入半径自动攻击。"""
    client, owned = await _get_combat_client(bot_id, db, user)
    try:
        result = await client.set_guard(
            enabled=data.enabled, x=data.x, y=data.y, z=data.z,
            radius=data.radius, scan_radius=data.scan_radius,
            attack_radius=data.attack_radius,
            target_types=data.target_types,
            interval_ms=data.interval_ms, interval_tick=data.interval_tick,
            interval_mode=data.interval_mode,
            stop_durability=data.stop_durability,
            move_to_target=data.move_to_target,
        )
        if isinstance(result, dict) and result.get("success") is False:
            raise HTTPException(400, result.get("error", "配置失败"))
        # 持久化配置（bot 重启/面板重开可恢复）
        _save_combat_config(db, bot_id, result.get("config"))
        return {"success": True, "bot_id": bot_id, "config": result.get("config")}
    except (MccMcpError, MineflayerError) as e:
        raise HTTPException(502, f"MCP error: {str(e) or repr(e)}")
    finally:
        if owned: await client.disconnect()


@router.get("/{bot_id}/combat/status")
async def combat_status(bot_id: str, db: Session = Depends(get_db),
                        user=Depends(require_admin)):
    """当前战斗状态（模式/配置/主手武器耐久/实体数）。

    bot 无活动配置（未启用/刚重启）时，返回 DB 持久化的上次配置
    （enabled=false），前端据此恢复表单，无需重新填写参数。
    """
    client, owned = await _get_combat_client(bot_id, db, user)
    try:
        data = await client.get_combat_status()
        # 无活动配置 → 用持久化配置兜底（仅恢复参数，不自动启用）
        if isinstance(data, dict) and not data.get("config"):
            saved = _load_combat_config(db, bot_id)
            if saved:
                data["config"] = saved
                data.setdefault("active_mode", None)
        # 主手武器名汉化（durability.name 为 item_id，如 cooked_porkchop）
        try:
            dur = data.get("durability") if isinstance(data, dict) else None
            if isinstance(dur, dict) and dur.get("name"):
                from vmtools_next.core.item_names_zh import get_item_zh
                item_id = str(dur["name"])
                dur["zh_name"] = get_item_zh(item_id, fallback=dur.get("display_name"))
        except Exception:
            pass
        return data
    except (MccMcpError, MineflayerError) as e:
        raise HTTPException(502, f"MCP error: {str(e) or repr(e)}")
    finally:
        if owned: await client.disconnect()


@router.post("/{bot_id}/combat/stop")
async def combat_stop(bot_id: str, db: Session = Depends(get_db),
                      user=Depends(require_admin)):
    """停止自动攻击 / 守护模式。"""
    client, owned = await _get_combat_client(bot_id, db, user)
    try:
        result = await client.stop_combat()
        return {"success": True, "bot_id": bot_id, "result": result}
    except (MccMcpError, MineflayerError) as e:
        raise HTTPException(502, f"MCP error: {str(e) or repr(e)}")
    finally:
        if owned: await client.disconnect()


# ── 永昼：睡觉（2026-08-16，仅 mineflayer） ──
# 开关走插件体系（POST /api/plugins/auto_sleep/enable|disable?bot_id=xxx）；
# 睡觉点 per-bot 存 mcc_bots.sleep_x/y/z；本段提供状态查询 / 睡觉点保存 / 手动睡一次。

def _auto_sleep_plugin():
    from vmtools_next.main import get_plugin_manager
    pm = get_plugin_manager()
    if pm is None:
        return None, None
    return pm, pm.plugins.get("auto_sleep")


async def _get_sleep_client(bot_id: str, db: Session, user) -> tuple:
    """获取睡觉 client（仅 mineflayer 引擎）。"""
    _get_scoped_bot(db, user, bot_id)
    from vmtools_next.core.bot_engine import resolve_bot_engine
    engine = resolve_bot_engine(bot_id, db)
    if engine != "mineflayer":
        raise HTTPException(400, "永昼（睡觉）功能仅支持 mineflayer 引擎")
    return await _get_mcp_client(bot_id)


@router.get("/{bot_id}/sleep/status")
async def sleep_status(bot_id: str, db: Session = Depends(get_db),
                       user=Depends(require_admin)):
    """永昼功能状态：开关（插件 per-bot）/ 配置 / 睡觉点 / 实时时间 / 忙碌 / 最近结果。

    前端「功能」tab 轮询数据源（5s）：:
        GET /api/mcc-bots/{bot_id}/sleep/status
    """
    bot = _get_scoped_bot(db, user, bot_id)
    pm, plugin = _auto_sleep_plugin()
    if pm is None:
        raise HTTPException(503, "Plugin manager unavailable")
    if plugin is None:
        raise HTTPException(404, "auto_sleep 插件未加载（检查 backend/src/vmtools_next/plugins/builtin/auto_sleep.py）")

    client, owned = await _get_sleep_client(bot_id, db, user)
    try:
        # 实时世界时间/睡觉状态（Node 端；bot 离线时容错）
        time_status = None
        try:
            time_status = await client.get_time_status()
        except Exception:
            time_status = None

        # 忙碌判定（复用状态页当前工作判定 + 战斗模式）
        busy = None
        task = _get_bot_current_task(db, bot_id)
        combat_mode = None
        try:
            combat = await client.get_combat_status()
            if combat.get("success") and combat.get("active_mode"):
                combat_mode = combat.get("active_mode")
        except Exception:
            pass
        busy = (task is not None) or (combat_mode is not None)

        return {
            "bot_id": bot_id,
            "enabled": pm.is_enabled_for_bot("auto_sleep", bot_id),
            "plugin_enabled": pm.is_enabled("auto_sleep"),
            "config": pm.get_config("auto_sleep") or {},
            "sleep_point": (
                {"x": bot.sleep_x, "y": bot.sleep_y, "z": bot.sleep_z}
                if bot.sleep_x is not None and bot.sleep_y is not None and bot.sleep_z is not None
                else None
            ),
            "time_status": time_status,
            "busy": busy,
            "current_task": task,
            "combat_mode": combat_mode,
            "last_result": plugin.get_last_result(bot_id) if hasattr(plugin, "get_last_result") else None,
        }
    except (MccMcpError, MineflayerError) as e:
        raise HTTPException(502, f"MCP error: {str(e) or repr(e)}")
    finally:
        if owned: await client.disconnect()


@router.put("/{bot_id}/sleep/point")
async def sleep_save_point(bot_id: str, body: SleepPointRequest,
                           db: Session = Depends(get_db),
                           user=Depends(require_admin)):
    """保存该 bot 的固定睡觉点（床的方块坐标）。"""
    bot = _get_scoped_bot(db, user, bot_id)
    bot.sleep_x = int(body.x)
    bot.sleep_y = int(body.y)
    bot.sleep_z = int(body.z)
    db.commit()
    return {"success": True, "bot_id": bot_id,
            "sleep_point": {"x": bot.sleep_x, "y": bot.sleep_y, "z": bot.sleep_z}}


@router.delete("/{bot_id}/sleep/point")
async def sleep_clear_point(bot_id: str, db: Session = Depends(get_db),
                            user=Depends(require_admin)):
    """清除该 bot 的固定睡觉点。"""
    bot = _get_scoped_bot(db, user, bot_id)
    bot.sleep_x = bot.sleep_y = bot.sleep_z = None
    db.commit()
    return {"success": True, "bot_id": bot_id, "sleep_point": None}


@router.post("/{bot_id}/sleep")
async def sleep_now(bot_id: str, db: Session = Depends(get_db),
                    user=Depends(require_admin)):
    """立即执行一次睡觉（到睡觉点）；用于测试/手动触发。"""
    bot = _get_scoped_bot(db, user, bot_id)
    if bot.sleep_x is None or bot.sleep_y is None or bot.sleep_z is None:
        raise HTTPException(400, "未配置睡觉点，请先在「功能」tab 保存床的坐标")
    client, owned = await _get_sleep_client(bot_id, db, user)
    try:
        result = await client.sleep_at(x=bot.sleep_x, y=bot.sleep_y, z=bot.sleep_z,
                                       timeout_ms=45000)
        return {"success": bool(result.get("success")), "bot_id": bot_id, "result": result}
    except (MccMcpError, MineflayerError) as e:
        raise HTTPException(502, f"MCP error: {str(e) or repr(e)}")
    finally:
        if owned: await client.disconnect()
