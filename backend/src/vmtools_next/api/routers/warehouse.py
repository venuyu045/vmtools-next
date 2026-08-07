"""Warehouse management API routes.

CRUD + materials / aisles / zones / scan-status, all scoped by organization
(site_admin → all, others → same org). Field names match the ORM model
(WarehouseModel) so the frontend contract is consistent.
"""
from __future__ import annotations

import json
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from vmtools_next.api.deps import get_db, get_current_user, require_admin
from vmtools_next.core.item_names_zh import get_item_zh, search_zh_keywords
from vmtools_next.data.models.auth import UserModel
from vmtools_next.data.models.warehouse import (
    ContainerItemDetailModel,
    MaterialItemModel,
    ScanStatusModel,
    StorageZoneModel,
    WarehouseModel,
)

router = APIRouter(prefix="/api/warehouses", tags=["warehouses"])
materials_router = APIRouter(prefix="/api/materials", tags=["materials"])


# ── Schemas ─────────────────────────────────────────────────────────────

class WarehouseCreate(BaseModel):
    name: str
    teleport_cmd: Optional[str] = None
    logistics_enabled: bool = False
    logistics_teleport_cmd: Optional[str] = None
    aisle_lines: list = Field(default_factory=list)


class WarehouseUpdate(BaseModel):
    name: Optional[str] = None
    teleport_cmd: Optional[str] = None
    logistics_enabled: Optional[bool] = None
    aisle_lines: Optional[list] = None


class WarehouseResponse(BaseModel):
    warehouse_id: str
    name: str
    last_scan_time: Optional[str] = None
    container_count: int = 0
    total_items: int = 0
    material_count: int = 0  # 物品种类数（管理页简略数据用）
    aisle_lines: list = Field(default_factory=list)
    group_id: Optional[str] = None
    organization_id: Optional[str] = None
    logistics_enabled: bool = False
    logistics_teleport_cmd: Optional[str] = None
    teleport_cmd: Optional[str] = None  # 前往仓库的传送指令（与 logistics_teleport_cmd 同值）


class MaterialResponse(BaseModel):
    item_id: str
    display_name: str
    item_name_zh: str = ""
    count: int


class MaterialsPage(BaseModel):
    items: list[MaterialResponse]
    total: int
    page: int
    page_size: int


class ZoneCreate(BaseModel):
    name: str = ""
    range_min_x: int = 0
    range_min_y: int = 0
    range_min_z: int = 0
    range_max_x: int = 0
    range_max_y: int = 0
    range_max_z: int = 0
    aisle_lines: list = Field(default_factory=list)


class ZoneUpdate(BaseModel):
    name: Optional[str] = None
    range_min_x: Optional[int] = None
    range_min_y: Optional[int] = None
    range_min_z: Optional[int] = None
    range_max_x: Optional[int] = None
    range_max_y: Optional[int] = None
    range_max_z: Optional[int] = None
    aisle_lines: Optional[list] = None


class ZoneResponse(BaseModel):
    zone_id: str
    warehouse_fk: str
    name: str
    range_min_x: int
    range_min_y: int
    range_min_z: int
    range_max_x: int
    range_max_y: int
    range_max_z: int
    aisle_lines: list = Field(default_factory=list)
    created_at: Optional[str] = None


class ScanStatusResponse(BaseModel):
    warehouse_id: str
    status: str
    progress: float
    current_pos: Optional[str] = None
    total_containers: int
    scanned_containers: int
    failed_containers: int
    items_scanned: int = 0
    started_at: Optional[str] = None
    finished_at: Optional[str] = None


# ── 物品搜索（仓库状态页） ──

class ItemSearchContainer(BaseModel):
    x: int
    y: int
    z: int
    count: int = 0
    slot: int = -1


class ItemSearchWarehouse(BaseModel):
    warehouse_id: str
    warehouse_name: str
    count: int = 0
    containers: list[ItemSearchContainer] = Field(default_factory=list)


class ItemSearchResult(BaseModel):
    item_id: str
    display_name: str
    item_name_zh: str
    total_count: int = 0
    warehouses: list[ItemSearchWarehouse] = Field(default_factory=list)


class ItemSearchPage(BaseModel):
    items: list[ItemSearchResult]
    total: int


# ── Helpers ─────────────────────────────────────────────────────────────

def _scoped_warehouse_query(db: Session, user: UserModel):
    """Warehouse query — organization isolation removed (all data visible)."""
    return db.query(WarehouseModel)


def _get_scoped_warehouse(db: Session, user: UserModel, warehouse_id: str) -> WarehouseModel:
    wh = _scoped_warehouse_query(db, user).filter(
        WarehouseModel.warehouse_id == warehouse_id).first()
    if not wh:
        raise HTTPException(404, "Warehouse not found")
    return wh


def _parse_aisle_lines(raw: Optional[str]) -> list:
    if not raw:
        return []
    try:
        value = json.loads(raw)
        return value if isinstance(value, list) else []
    except Exception:
        return []


def _material_counts(db: Session, wh_ids: list[str]) -> dict[str, int]:
    """批量统计每个仓库的物品种类数（material_items 行数）。"""
    if not wh_ids:
        return {}
    rows = db.query(
        MaterialItemModel.warehouse_fk,
        func.count(MaterialItemModel.id),
    ).filter(
        MaterialItemModel.warehouse_fk.in_(wh_ids),
    ).group_by(MaterialItemModel.warehouse_fk).all()
    return {wh_fk: int(c) for wh_fk, c in rows}


def _to_response(wh: WarehouseModel, material_count: int | None = None) -> WarehouseResponse:
    return WarehouseResponse(
        warehouse_id=wh.warehouse_id,
        name=wh.name,
        last_scan_time=wh.last_scan_time.isoformat() if wh.last_scan_time else None,
        container_count=wh.container_count or 0,
        total_items=wh.total_items or 0,
        material_count=material_count if material_count is not None else 0,
        aisle_lines=_parse_aisle_lines(wh.aisle_lines),
        group_id=wh.group_id,
        organization_id=wh.organization_id,
        logistics_enabled=wh.logistics_enabled,
        logistics_teleport_cmd=wh.logistics_teleport_cmd,
        teleport_cmd=wh.logistics_teleport_cmd,
    )


# ── CRUD ────────────────────────────────────────────────────────────────

@router.get("", response_model=list[WarehouseResponse])
def list_warehouses(db: Session = Depends(get_db), user=Depends(get_current_user)):
    whs = _scoped_warehouse_query(db, user).all()
    counts = _material_counts(db, [w.warehouse_id for w in whs])
    return [_to_response(w, counts.get(w.warehouse_id, 0)) for w in whs]


@router.post("", response_model=WarehouseResponse)
def create_warehouse(data: WarehouseCreate, db: Session = Depends(get_db),
                     user=Depends(get_current_user)):
    wh = WarehouseModel(
        warehouse_id=str(uuid.uuid4()),
        name=data.name,
        aisle_lines=json.dumps(data.aisle_lines or [], ensure_ascii=False),
        organization_id=user.organization_id,
        logistics_enabled=data.logistics_enabled,
        logistics_teleport_cmd=data.teleport_cmd or data.logistics_teleport_cmd,
    )
    db.add(wh)
    db.commit()
    db.refresh(wh)
    return _to_response(wh, 0)


@router.put("/{warehouse_id}", response_model=WarehouseResponse)
def update_warehouse(warehouse_id: str, data: WarehouseUpdate,
                     db: Session = Depends(get_db), user=Depends(require_admin)):
    """Update warehouse metadata (name / teleport_cmd / aisle_lines / logistics)."""
    wh = _get_scoped_warehouse(db, user, warehouse_id)
    if data.name is not None:
        wh.name = data.name
    if data.teleport_cmd is not None:
        wh.logistics_teleport_cmd = data.teleport_cmd
    if data.logistics_enabled is not None:
        wh.logistics_enabled = data.logistics_enabled
    if data.aisle_lines is not None:
        wh.aisle_lines = json.dumps(data.aisle_lines, ensure_ascii=False)
    db.commit()
    db.refresh(wh)
    counts = _material_counts(db, [wh.warehouse_id])
    return _to_response(wh, counts.get(wh.warehouse_id, 0))


@router.get("/scan-queue")
async def list_scan_queue(db: Session = Depends(get_db),
                          user=Depends(get_current_user)):
    """返回扫描队列列表（由 ScanQueueManager 调度）。注意：须定义在 /{warehouse_id} 之前。"""
    from vmtools_next.main import get_scan_queue_manager
    qm = get_scan_queue_manager()
    if not qm:
        return {"items": []}
    return {"items": await qm.list_queue()}


@router.get("/items/search", response_model=ItemSearchPage)
def search_item_details(q: str = "", limit: int = 50,
                        db: Session = Depends(get_db),
                        user=Depends(get_current_user)):
    """跨仓库搜索物品（中文名/英文名/item id 均可）。

    返回按「总储量降序」排序的物品列表；每个物品下按「仓库储量降序」列出仓库，
    并在有明细数据（重新扫描后）时列出每个仓库中存放该物品的箱子坐标与储量。
    """
    from collections import defaultdict
    q = (q or "").strip()
    limit = max(1, min(limit, 200))
    if not q:
        return ItemSearchPage(items=[], total=0)

    like = f"%{q}%"
    zh_ids = search_zh_keywords(q)  # 中文关键词 → item_id 候选（不带命名空间）
    conditions = [MaterialItemModel.item_id.like(like), MaterialItemModel.display_name.like(like)]
    if zh_ids:
        # 兼容带/不带 minecraft: 前缀（仓库数据为 minecraft:xxx）
        prefixed = [f"minecraft:{k}" for k in zh_ids]
        conditions.append(MaterialItemModel.item_id.in_(set(zh_ids + prefixed)))
    # 性能：命中行按储量降序限量取回，避免大仓库全表物化后再截断（L1）
    rows = (
        db.query(MaterialItemModel).filter(or_(*conditions))
        .order_by(MaterialItemModel.count.desc())
        .limit(limit * 10).all()
    )

    # item_id → 仓库聚合 {warehouse_fk: count} + display_name
    wh_by_item: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    names: dict[str, str] = {}
    for r in rows:
        if not r.item_id:
            continue
        wh_by_item[r.item_id][r.warehouse_fk] += r.count or 0
        names.setdefault(r.item_id, r.display_name or r.item_id)

    if not wh_by_item:
        return ItemSearchPage(items=[], total=0)

    # 仓库名缓存
    whs = {w.warehouse_id: w for w in db.query(WarehouseModel).all()}

    # 有明细数据的 item → 箱子定位（container_item_details）
    detail_item_ids = list(wh_by_item.keys())
    detail_rows = db.query(ContainerItemDetailModel).filter(
        ContainerItemDetailModel.item_id.in_(detail_item_ids),
    ).all() if detail_item_ids else []
    detail_by_item: dict[str, list] = defaultdict(list)
    for d in detail_rows:
        detail_by_item[d.item_id].append(d)

    # 组装结果，按总储量降序
    results: list[ItemSearchResult] = []
    for item_id, wh_counts in wh_by_item.items():
        total = sum(wh_counts.values())
        warehouse_list: list[ItemSearchWarehouse] = []
        for wh_fk, count in sorted(wh_counts.items(), key=lambda kv: kv[1], reverse=True):
            w = whs.get(wh_fk)
            containers = []
            for d in sorted(detail_by_item.get(item_id, []),
                            key=lambda d: (d.warehouse_fk != wh_fk, - (d.count or 0))):
                if d.warehouse_fk == wh_fk:
                    containers.append(ItemSearchContainer(
                        x=d.container_x, y=d.container_y, z=d.container_z,
                        count=d.count or 0, slot=d.slot or -1,
                    ))
            warehouse_list.append(ItemSearchWarehouse(
                warehouse_id=wh_fk,
                warehouse_name=w.name if w else wh_fk[:8],
                count=count,
                containers=containers,
            ))
        results.append(ItemSearchResult(
            item_id=item_id,
            display_name=names[item_id],
            item_name_zh=get_item_zh(item_id, names[item_id]),
            total_count=total,
            warehouses=warehouse_list,
        ))

    results.sort(key=lambda r: r.total_count, reverse=True)
    return ItemSearchPage(items=results[:limit], total=len(results))


@router.get("/{warehouse_id}", response_model=WarehouseResponse)
def get_warehouse(warehouse_id: str, db: Session = Depends(get_db),
                  user=Depends(get_current_user)):
    wh = _get_scoped_warehouse(db, user, warehouse_id)
    counts = _material_counts(db, [wh.warehouse_id])
    return _to_response(wh, counts.get(wh.warehouse_id, 0))


@router.delete("/{warehouse_id}")
def delete_warehouse(warehouse_id: str, db: Session = Depends(get_db),
                     user=Depends(require_admin)):
    wh = _get_scoped_warehouse(db, user, warehouse_id)
    db.delete(wh)
    db.commit()
    return {"status": "deleted"}


# ── Materials ───────────────────────────────────────────────────────────

@router.get("/{warehouse_id}/materials", response_model=MaterialsPage)
def list_materials(warehouse_id: str, page: int = 1, page_size: int = 500,
                   db: Session = Depends(get_db), user=Depends(get_current_user)):
    """List aggregated materials for a warehouse (paginated)."""
    wh = _get_scoped_warehouse(db, user, warehouse_id)
    page = max(1, page)
    page_size = max(1, min(page_size, 5000))

    q = db.query(MaterialItemModel).filter(MaterialItemModel.warehouse_fk == wh.warehouse_id)
    total = q.count()
    rows = q.order_by(MaterialItemModel.count.desc()).offset((page - 1) * page_size).limit(page_size).all()

    return MaterialsPage(
        items=[MaterialResponse(item_id=r.item_id, display_name=r.display_name or r.item_id,
                                item_name_zh=get_item_zh(r.item_id, r.display_name or r.item_id),
                                count=r.count or 0) for r in rows],
        total=total, page=page, page_size=page_size,
    )


@materials_router.get("/search", response_model=MaterialsPage)
def search_materials(q: str = "", page: int = 1, page_size: int = 100,
                     db: Session = Depends(get_db), user=Depends(get_current_user)):
    """Search materials across warehouses visible to the user."""
    page = max(1, page)
    page_size = max(1, min(page_size, 500))

    wh_ids = [w.warehouse_id for w in _scoped_warehouse_query(db, user).all()]
    query = db.query(MaterialItemModel).filter(
        MaterialItemModel.warehouse_fk.in_(wh_ids)) if wh_ids \
        else db.query(MaterialItemModel).filter(MaterialItemModel.warehouse_fk.is_(None))

    if q:
        like = f"%{q}%"
        query = query.filter(
            MaterialItemModel.item_id.like(like) | MaterialItemModel.display_name.like(like)
        )

    total = query.count()
    rows = query.order_by(MaterialItemModel.count.desc()).offset((page - 1) * page_size).limit(page_size).all()
    return MaterialsPage(
        items=[MaterialResponse(item_id=r.item_id, display_name=r.display_name or r.item_id,
                                item_name_zh=get_item_zh(r.item_id, r.display_name or r.item_id),
                                count=r.count or 0) for r in rows],
        total=total, page=page, page_size=page_size,
    )


# ── Aisles ──────────────────────────────────────────────────────────────

@router.get("/{warehouse_id}/aisles")
def get_aisles(warehouse_id: str, db: Session = Depends(get_db),
               user=Depends(get_current_user)):
    wh = _get_scoped_warehouse(db, user, warehouse_id)
    return {"warehouse_id": wh.warehouse_id, "aisle_lines": _parse_aisle_lines(wh.aisle_lines)}


class AislesUpdate(BaseModel):
    aisle_lines: list = Field(default_factory=list)


@router.put("/{warehouse_id}/aisles")
def update_aisles(warehouse_id: str, data: AislesUpdate,
                  db: Session = Depends(get_db), user=Depends(require_admin)):
    wh = _get_scoped_warehouse(db, user, warehouse_id)
    wh.aisle_lines = json.dumps(data.aisle_lines or [], ensure_ascii=False)
    db.commit()
    return {"warehouse_id": wh.warehouse_id, "aisle_lines": data.aisle_lines or []}


# ── Zones ───────────────────────────────────────────────────────────────

def _zone_response(z: StorageZoneModel) -> ZoneResponse:
    return ZoneResponse(
        zone_id=z.zone_id,
        warehouse_fk=z.warehouse_fk,
        name=z.name,
        range_min_x=z.range_min_x, range_min_y=z.range_min_y, range_min_z=z.range_min_z,
        range_max_x=z.range_max_x, range_max_y=z.range_max_y, range_max_z=z.range_max_z,
        aisle_lines=_parse_aisle_lines(z.aisle_lines),
        created_at=z.created_at.isoformat() if z.created_at else None,
    )


@router.get("/{warehouse_id}/zones", response_model=list[ZoneResponse])
def list_zones(warehouse_id: str, db: Session = Depends(get_db),
               user=Depends(get_current_user)):
    wh = _get_scoped_warehouse(db, user, warehouse_id)
    zones = db.query(StorageZoneModel).filter(
        StorageZoneModel.warehouse_fk == wh.warehouse_id).all()
    return [_zone_response(z) for z in zones]


@router.post("/{warehouse_id}/zones", response_model=ZoneResponse)
def create_zone(warehouse_id: str, data: ZoneCreate,
                db: Session = Depends(get_db), user=Depends(require_admin)):
    wh = _get_scoped_warehouse(db, user, warehouse_id)
    zone = StorageZoneModel(
        zone_id=str(uuid.uuid4()),
        warehouse_fk=wh.warehouse_id,
        name=data.name,
        range_min_x=data.range_min_x, range_min_y=data.range_min_y, range_min_z=data.range_min_z,
        range_max_x=data.range_max_x, range_max_y=data.range_max_y, range_max_z=data.range_max_z,
        aisle_lines=json.dumps(data.aisle_lines or [], ensure_ascii=False),
    )
    db.add(zone)
    db.commit()
    db.refresh(zone)
    return _zone_response(zone)


@router.put("/{warehouse_id}/zones/{zone_id}", response_model=ZoneResponse)
def update_zone(warehouse_id: str, zone_id: str, data: ZoneUpdate,
                db: Session = Depends(get_db), user=Depends(require_admin)):
    wh = _get_scoped_warehouse(db, user, warehouse_id)
    zone = db.query(StorageZoneModel).filter(
        StorageZoneModel.zone_id == zone_id,
        StorageZoneModel.warehouse_fk == wh.warehouse_id).first()
    if not zone:
        raise HTTPException(404, "Zone not found")
    for field_name in ("name", "range_min_x", "range_min_y", "range_min_z",
                       "range_max_x", "range_max_y", "range_max_z"):
        value = getattr(data, field_name)
        if value is not None:
            setattr(zone, field_name, value)
    if data.aisle_lines is not None:
        zone.aisle_lines = json.dumps(data.aisle_lines, ensure_ascii=False)
    db.commit()
    db.refresh(zone)
    return _zone_response(zone)


@router.delete("/{warehouse_id}/zones/{zone_id}")
def delete_zone(warehouse_id: str, zone_id: str,
                db: Session = Depends(get_db), user=Depends(require_admin)):
    wh = _get_scoped_warehouse(db, user, warehouse_id)
    zone = db.query(StorageZoneModel).filter(
        StorageZoneModel.zone_id == zone_id,
        StorageZoneModel.warehouse_fk == wh.warehouse_id).first()
    if not zone:
        raise HTTPException(404, "Zone not found")
    db.delete(zone)
    db.commit()
    return {"status": "deleted"}


# ── Scan status ─────────────────────────────────────────────────────────

@router.get("/{warehouse_id}/scan-status", response_model=ScanStatusResponse)
def get_scan_status(warehouse_id: str, db: Session = Depends(get_db),
                    user=Depends(get_current_user)):
    wh = _get_scoped_warehouse(db, user, warehouse_id)
    st = db.query(ScanStatusModel).filter(
        ScanStatusModel.warehouse_fk == wh.warehouse_id).first()
    if not st:
        return ScanStatusResponse(warehouse_id=wh.warehouse_id, status="idle", progress=0.0,
                                  current_pos=None, total_containers=0,
                                  scanned_containers=0, failed_containers=0)
    return ScanStatusResponse(
        warehouse_id=wh.warehouse_id,
        status=st.status,
        progress=st.progress or 0.0,
        current_pos=st.current_pos,
        total_containers=st.total_containers or 0,
        scanned_containers=st.scanned_containers or 0,
        failed_containers=st.failed_containers or 0,
        items_scanned=st.items_scanned or 0,
        started_at=st.started_at.isoformat() if st.started_at else None,
        finished_at=st.finished_at.isoformat() if st.finished_at else None,
    )