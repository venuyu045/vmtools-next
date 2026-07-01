"""MCC Bot management API routes."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from vmtools_next.api.deps import get_db, get_current_user
from vmtools_next.api.schemas.mcc import MccBotCreate, MccBotResponse, MccBotConnectRequest
from vmtools_next.data.models.logistics import MccBotModel

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
