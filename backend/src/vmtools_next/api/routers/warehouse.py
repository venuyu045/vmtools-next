"""Warehouse management API routes."""
from __future__ import annotations

import uuid
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional
from sqlalchemy.orm import Session

from vmtools_next.api.deps import get_db, get_current_user
from vmtools_next.data.models.warehouse import WarehouseModel

router = APIRouter(prefix="/api/warehouses", tags=["warehouses"])


class WarehouseCreate(BaseModel):
    name: str
    server_address: str = ""
    x: int = 0
    y: int = 0
    z: int = 0
    teleport_command: str = ""
    organization_id: Optional[str] = None


class WarehouseResponse(BaseModel):
    id: str
    name: str
    server_address: str
    x: int
    y: int
    z: int
    teleport_command: str
    organization_id: Optional[str]


@router.get("", response_model=list[WarehouseResponse])
def list_warehouses(db: Session = Depends(get_db), user=Depends(get_current_user)):
    whs = db.query(WarehouseModel).all()
    return [WarehouseResponse(
        id=w.id, name=w.name, server_address=w.server_address,
        x=w.x, y=w.y, z=w.z, teleport_command=w.teleport_command,
        organization_id=w.organization_id,
    ) for w in whs]


@router.post("", response_model=WarehouseResponse)
def create_warehouse(data: WarehouseCreate, db: Session = Depends(get_db),
                      user=Depends(get_current_user)):
    wh = WarehouseModel(id=str(uuid.uuid4()), **data.model_dump())
    db.add(wh)
    db.commit()
    db.refresh(wh)
    return WarehouseResponse(
        id=wh.id, name=wh.name, server_address=wh.server_address,
        x=wh.x, y=wh.y, z=wh.z, teleport_command=wh.teleport_command,
        organization_id=wh.organization_id,
    )


@router.get("/{warehouse_id}", response_model=WarehouseResponse)
def get_warehouse(warehouse_id: str, db: Session = Depends(get_db),
                   user=Depends(get_current_user)):
    wh = db.query(WarehouseModel).filter(WarehouseModel.id == warehouse_id).first()
    if not wh:
        raise HTTPException(404, "Warehouse not found")
    return WarehouseResponse(
        id=wh.id, name=wh.name, server_address=wh.server_address,
        x=wh.x, y=wh.y, z=wh.z, teleport_command=wh.teleport_command,
        organization_id=wh.organization_id,
    )


@router.delete("/{warehouse_id}")
def delete_warehouse(warehouse_id: str, db: Session = Depends(get_db),
                      user=Depends(get_current_user)):
    wh = db.query(WarehouseModel).filter(WarehouseModel.id == warehouse_id).first()
    if not wh:
        raise HTTPException(404, "Warehouse not found")
    db.delete(wh)
    db.commit()
    return {"status": "deleted"}
