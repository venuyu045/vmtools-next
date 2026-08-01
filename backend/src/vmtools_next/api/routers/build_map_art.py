"""Map Art Build Task API routes.

Per implementation-plan.md Section 5 (API Design).
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from pydantic import BaseModel
from sqlalchemy.orm import Session

from vmtools_next.api.deps import get_db, get_current_user
from vmtools_next.data.models.build_map_art import (
    MapArtTask, MapArtMaterial, MapArtBotAssignment, MapArtBlockState,
)
from vmtools_next.adapters.litematica.litematica_parser import LitematicaParser
from vmtools_next.core.map_art_coordinator import (
    MapArtCoordinator,
    partition_rectangular,
    get_coordinator,
    register_coordinator,
    unregister_coordinator,
)

logger = logging.getLogger("vmtools.map_art_api")
router = APIRouter(prefix="/api/build/map-art", tags=["map-art"])


# ──────────────────────────────────────────────
# Pydantic schemas
# ──────────────────────────────────────────────

class MapArtTaskCreate(BaseModel):
    name: str
    projection_file_path: str
    origin_x: int = 0
    origin_y: int = 64
    origin_z: int = 0
    bot_ids: list[str] = []
    organization_id: Optional[str] = None


class MapArtTaskResponse(BaseModel):
    task_id: str
    name: str
    status: str
    projection_name: str
    projection_author: str
    projection_size_x: int
    projection_size_z: int
    total_blocks: int
    placed_blocks: int
    created_at: str


class TaskControlRequest(BaseModel):
    action: str  # start | pause | resume | stop


class BotManageRequest(BaseModel):
    action: str  # add | remove
    bot_id: str


# ──────────────────────────────────────────────
# Routes
# ──────────────────────────────────────────────

@router.post("/tasks", response_model=MapArtTaskResponse)
async def create_task(
    data: MapArtTaskCreate,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    """Create a new map art build task from a Litematica projection file."""
    # Parse projection to get metadata and materials
    try:
        parsed = await LitematicaParser.parse_file(data.projection_file_path)
        info = await LitematicaParser.get_projection_info(
            data.projection_file_path,
            origin_x=data.origin_x,
            origin_y=data.origin_y,
            origin_z=data.origin_z,
        )
        reqs = await LitematicaParser.get_material_requirements(data.projection_file_path)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to parse projection: {e}")

    # Create task
    task = MapArtTask(
        name=data.name,
        projection_file_path=data.projection_file_path,
        projection_name=info.name,
        projection_author=info.author,
        projection_size_x=info.size_x,
        projection_size_y=info.size_y,
        projection_size_z=info.size_z,
        projection_total_blocks=info.total_blocks,
        origin_x=data.origin_x,
        origin_y=data.origin_y,
        origin_z=data.origin_z,
        total_blocks=info.total_blocks,
        organization_id=data.organization_id or getattr(user, "organization_id", None),
        created_by=getattr(user, "game_id", str(user)),
    )
    db.add(task)
    db.flush()

    # Material requirements
    for req in reqs:
        mat = MapArtMaterial(
            task_id=task.task_id,
            item_id=req.item_id,
            display_name=req.display_name,
            required_count=req.count,
        )
        db.add(mat)

    # Initial bot assignments (regions)
    n_bots = max(len(data.bot_ids), 1)
    regions = partition_rectangular(info.size_x, info.size_z, n_bots)
    for i, bot_id in enumerate(data.bot_ids or ["unassigned"]):
        r = regions[i]
        ba = MapArtBotAssignment(
            task_id=task.task_id,
            bot_id=bot_id,
            region_x_start=r.x_start,
            region_x_end=r.x_end,
            region_z_start=r.z_start,
            region_z_end=r.z_end,
            blocks_total=r.block_count,
        )
        db.add(ba)

    # Block states
    layers = parsed.layers
    for y_offset, blocks in layers.items():
        for wx, wy, wz, block_id in blocks:
            bs = MapArtBlockState(
                task_id=task.task_id,
                x=wx, y=wy, z=wz,
                expected_block=block_id,
            )
            db.add(bs)

    db.commit()

    return MapArtTaskResponse(
        task_id=task.task_id,
        name=task.name,
        status=task.status,
        projection_name=task.projection_name,
        projection_author=task.projection_author or "",
        projection_size_x=task.projection_size_x,
        projection_size_z=task.projection_size_z,
        total_blocks=task.total_blocks,
        placed_blocks=task.placed_blocks,
        created_at=task.created_at.isoformat() if task.created_at else "",
    )


@router.get("/tasks")
def list_tasks(
    status: Optional[str] = None,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    """List map art build tasks, optionally filtered by status."""
    q = db.query(MapArtTask)
    if status:
        q = q.filter(MapArtTask.status == status)
    tasks = q.order_by(MapArtTask.created_at.desc()).limit(50).all()
    return {
        "tasks": [
            {
                "task_id": t.task_id,
                "name": t.name,
                "status": t.status,
                "projection_name": t.projection_name,
                "total_blocks": t.total_blocks,
                "placed_blocks": t.placed_blocks,
                "projection_size_x": t.projection_size_x,
                "projection_size_z": t.projection_size_z,
                "created_at": t.created_at.isoformat() if t.created_at else "",
            }
            for t in tasks
        ],
        "total": len(tasks),
    }


@router.get("/tasks/{task_id}")
def get_task(task_id: str, db: Session = Depends(get_db)):
    """Get full task details including materials and bot assignments."""
    task = db.query(MapArtTask).filter(MapArtTask.task_id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    materials = db.query(MapArtMaterial).filter(
        MapArtMaterial.task_id == task_id
    ).all()
    bots = db.query(MapArtBotAssignment).filter(
        MapArtBotAssignment.task_id == task_id
    ).all()

    return {
        "task_id": task.task_id,
        "name": task.name,
        "description": task.description,
        "status": task.status,
        "error_message": task.error_message,
        "projection": {
            "file_path": task.projection_file_path,
            "name": task.projection_name,
            "author": task.projection_author,
            "size_x": task.projection_size_x,
            "size_y": task.projection_size_y,
            "size_z": task.projection_size_z,
            "total_blocks": task.projection_total_blocks,
        },
        "origin": {"x": task.origin_x, "y": task.origin_y, "z": task.origin_z},
        "progress": {
            "total_blocks": task.total_blocks,
            "placed_blocks": task.placed_blocks,
            "verified_blocks": task.verified_blocks,
        },
        "materials": [
            {
                "item_id": m.item_id,
                "display_name": m.display_name,
                "required": m.required_count,
                "placed": m.placed_count,
                "color_hex": m.color_hex,
            }
            for m in materials
        ],
        "bots": [
            {
                "bot_id": b.bot_id,
                "bot_name": b.bot_name,
                "state": b.state,
                "region": {
                    "x_start": b.region_x_start, "x_end": b.region_x_end,
                    "z_start": b.region_z_start, "z_end": b.region_z_end,
                },
                "blocks_placed": b.blocks_placed,
                "blocks_total": b.blocks_total,
                "current_row": b.current_row,
                "place_rate": b.place_rate,
            }
            for b in bots
        ],
        "created_at": task.created_at.isoformat() if task.created_at else "",
        "started_at": task.started_at.isoformat() if task.started_at else None,
        "completed_at": task.completed_at.isoformat() if task.completed_at else None,
    }


@router.post("/tasks/{task_id}/control")
async def control_task(
    task_id: str,
    data: TaskControlRequest,
    db: Session = Depends(get_db),
):
    """Control a build task: start, pause, resume, stop."""
    task = db.query(MapArtTask).filter(MapArtTask.task_id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    coordinator = get_coordinator(task_id)

    if data.action == "start":
        if task.status not in ("draft", "pending"):
            raise HTTPException(status_code=400, detail=f"Cannot start task in '{task.status}' state")
        # Spawn coordinator
        # Parse projection
        parsed = await LitematicaParser.parse_file(task.projection_file_path)
        coord = MapArtCoordinator(
            task_id=task_id,
            projection_data={
                "layers": parsed.layers,
                "regions": parsed.regions,
            },
            origin_x=task.origin_x,
            origin_y=task.origin_y,
            origin_z=task.origin_z,
        )
        # 按每个 bot 的引擎从对应 session pool 取 client（MCC MCP vs mineflayer WS）
        from vmtools_next.main import get_pool_for_engine
        from vmtools_next.core.bot_engine import resolve_bot_engine
        bot_mcps = {}
        assignments = db.query(MapArtBotAssignment).filter(
            MapArtBotAssignment.task_id == task_id
        ).all()
        for ba in assignments:
            pool = get_pool_for_engine(resolve_bot_engine(ba.bot_id, db))
            client = pool.get_client(ba.bot_id) if pool else None
            if client:
                bot_mcps[ba.bot_id] = (ba.bot_name or ba.bot_id, client)

        if not bot_mcps:
            raise HTTPException(status_code=400, detail="No bots available to start task")

        await coord.start(bot_mcps)
        register_coordinator(task_id, coord)
        task.status = "running"
        task.started_at = datetime.now(timezone.utc)

    elif data.action == "pause":
        if coordinator:
            await coordinator.pause()
        task.status = "paused"

    elif data.action == "resume":
        if coordinator:
            await coordinator.resume()
        task.status = "running"

    elif data.action == "stop":
        if coordinator:
            await coordinator.stop()
            unregister_coordinator(task_id)
        task.status = "cancelled"
        task.completed_at = datetime.now(timezone.utc)

    else:
        raise HTTPException(status_code=400, detail=f"Unknown action: {data.action}")

    db.commit()
    return {"task_id": task_id, "status": task.status, "message": f"Task {data.action}ed"}


@router.delete("/tasks/{task_id}")
def delete_task(task_id: str, db: Session = Depends(get_db)):
    """Delete a task (only draft/cancelled/completed)."""
    task = db.query(MapArtTask).filter(MapArtTask.task_id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    if task.status not in ("draft", "cancelled", "completed"):
        raise HTTPException(status_code=400, detail=f"Cannot delete task in '{task.status}' state")
    unregister_coordinator(task_id)
    db.delete(task)
    db.commit()
    return {"deleted": task_id}


@router.get("/tasks/{task_id}/blocks")
def get_task_blocks(task_id: str, db: Session = Depends(get_db)):
    """Return all block states for a task (for 3D frontend initialization).

    Returns full block list so the Three.js canvas can render immediately.
    """
    task = db.query(MapArtTask).filter(MapArtTask.task_id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    blocks = db.query(MapArtBlockState).filter(
        MapArtBlockState.task_id == task_id
    ).all()

    # Get bot assignments for region outlines
    bots = db.query(MapArtBotAssignment).filter(
        MapArtBotAssignment.task_id == task_id
    ).all()

    return {
        "task_id": task_id,
        "blocks": [
            {"x": b.x, "y": b.y, "z": b.z,
             "expected": b.expected_block, "actual": b.actual_block,
             "placed": b.placed, "verified": b.verified}
            for b in blocks
        ],
        "bots": [
            {"bot_id": ba.bot_id, "bot_name": ba.bot_name, "state": ba.state,
             "region": {"x_start": ba.region_x_start, "x_end": ba.region_x_end,
                        "z_start": ba.region_z_start, "z_end": ba.region_z_end}}
            for ba in bots
        ],
        "origin": {"x": task.origin_x, "y": task.origin_y, "z": task.origin_z},
        "size": {"x": task.projection_size_x, "z": task.projection_size_z},
        "total": len(blocks),
        "placed": task.placed_blocks or 0,
    }


# ──────────────────────────────────────────────
# Projection upload
# ──────────────────────────────────────────────

@router.post("/projections/upload")
async def upload_projection(file: UploadFile = File(...)):
    """Upload a .litematic file and return its metadata + material requirements.

    File is saved to a configured upload directory.
    """
    import os
    from pathlib import Path

    # Save to uploads directory (absolute path)
    BASE = Path(__file__).resolve().parent.parent.parent.parent.parent  # backend/
    upload_dir = BASE / "uploads" / "build_projections"
    upload_dir.mkdir(parents=True, exist_ok=True)
    file_path = upload_dir / file.filename
    with open(file_path, "wb") as f:
        content = await file.read()
        f.write(content)

    # Return absolute path
    abs_path = str(file_path.resolve())

    # Parse and return metadata
    parsed = await LitematicaParser.parse_file(abs_path)
    info = await LitematicaParser.get_projection_info(abs_path)
    reqs = await LitematicaParser.get_material_requirements(abs_path)

    return {
        "file_path": abs_path,
        "projection_info": {
            "name": info.name,
            "author": info.author,
            "total_blocks": info.total_blocks,
            "size": {"x": info.size_x, "y": info.size_y, "z": info.size_z},
        },
        "material_requirements": [
            {
                "item_id": r.item_id,
                "display_name": r.display_name,
                "count": r.count,
            }
            for r in reqs
        ],
    }
