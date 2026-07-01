"""Projection management API routes.

Provides file upload, parsing, and material comparison for .litematic files.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from pydantic import BaseModel
from sqlalchemy.orm import Session

from vmtools_next.api.deps import get_db, get_current_user
from vmtools_next.adapters.litematica.litematica_parser import LitematicaParser
from vmtools_next.infra.logging import get_logger

logger = get_logger("api.projection")
router = APIRouter(prefix="/api/projections", tags=["projections"])

# In-memory storage for projections (could be moved to DB later)
_projections: dict[str, dict] = {}


class ProjectionResponse(BaseModel):
    id: str
    name: str
    author: str
    total_blocks: int
    total_volume: int
    region_count: int
    material_count: int
    uploaded_at: str


class ProjectionDetailResponse(BaseModel):
    id: str
    name: str
    author: str
    description: str
    total_blocks: int
    total_volume: int
    region_count: int
    region_names: list[str]
    materials: list[dict]
    uploaded_at: str


class CompareResult(BaseModel):
    item_id: str
    display_name: str
    required_count: int
    available_count: int
    missing_count: int
    sufficient: bool


@router.post("/upload", response_model=ProjectionResponse)
async def upload_projection(
    file: UploadFile = File(...),
    user=Depends(get_current_user),
):
    """Upload a .litematic file and parse its materials."""
    if not file.filename or not file.filename.endswith(".litematic"):
        raise HTTPException(400, "Only .litematic files are accepted")

    contents = await file.read()
    if len(contents) > 50 * 1024 * 1024:
        raise HTTPException(400, "File too large (max 50MB)")

    # Save to temp file for parsing
    import tempfile
    import pathlib
    with tempfile.NamedTemporaryFile(suffix=".litematic", delete=False) as tmp:
        tmp.write(contents)
        tmp_path = tmp.name

    try:
        parsed = await LitematicaParser.parse_file(tmp_path)
        reqs = await LitematicaParser.get_material_requirements(tmp_path)
    except Exception as e:
        pathlib.Path(tmp_path).unlink(missing_ok=True)
        raise HTTPException(400, f"Failed to parse .litematic: {e}")
    finally:
        pathlib.Path(tmp_path).unlink(missing_ok=True)

    proj_id = str(uuid.uuid4())
    materials = [{"item_id": r.item_id, "display_name": r.display_name, "count": r.count} for r in reqs]

    _projections[proj_id] = {
        "id": proj_id,
        "name": parsed.name or file.filename,
        "author": parsed.author,
        "description": parsed.description,
        "total_blocks": parsed.total_blocks,
        "total_volume": parsed.total_volume,
        "region_count": len(parsed.regions),
        "region_names": list(parsed.regions.keys()),
        "materials": materials,
        "uploaded_at": datetime.now(timezone.utc).isoformat(),
    }

    logger.info("Uploaded projection: %s (%d blocks, %d materials)",
                parsed.name, parsed.total_blocks, len(materials))

    return ProjectionResponse(
        id=proj_id,
        name=parsed.name or file.filename,
        author=parsed.author,
        total_blocks=parsed.total_blocks,
        total_volume=parsed.total_volume,
        region_count=len(parsed.regions),
        material_count=len(materials),
        uploaded_at=_projections[proj_id]["uploaded_at"],
    )


@router.get("", response_model=list[ProjectionResponse])
def list_projections(user=Depends(get_current_user)):
    """List all uploaded projections."""
    return [
        ProjectionResponse(
            id=p["id"],
            name=p["name"],
            author=p["author"],
            total_blocks=p["total_blocks"],
            total_volume=p["total_volume"],
            region_count=p["region_count"],
            material_count=len(p["materials"]),
            uploaded_at=p["uploaded_at"],
        )
        for p in _projections.values()
    ]


@router.get("/{projection_id}", response_model=ProjectionDetailResponse)
def get_projection(projection_id: str, user=Depends(get_current_user)):
    """Get a projection with its full material list."""
    p = _projections.get(projection_id)
    if not p:
        raise HTTPException(404, "Projection not found")
    return ProjectionDetailResponse(**p)


@router.get("/{projection_id}/compare")
def compare_projection(
    projection_id: str,
    warehouse_id: str = "",
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    """Compare projection materials against warehouse inventory."""
    p = _projections.get(projection_id)
    if not p:
        raise HTTPException(404, "Projection not found")

    # Get warehouse materials if warehouse_id provided
    available: dict[str, int] = {}
    if warehouse_id:
        from vmtools_next.data.models.warehouse import MaterialItemModel
        items = db.query(MaterialItemModel).filter(MaterialItemModel.warehouse_fk == warehouse_id).all()
        for item in items:
            available[item.item_id] = available.get(item.item_id, 0) + item.count

    results = []
    for mat in p["materials"]:
        req_count = mat["count"]
        avail_count = available.get(mat["item_id"], 0)
        results.append(CompareResult(
            item_id=mat["item_id"],
            display_name=mat["display_name"],
            required_count=req_count,
            available_count=avail_count,
            missing_count=max(0, req_count - avail_count),
            sufficient=avail_count >= req_count,
        ))

    return results
