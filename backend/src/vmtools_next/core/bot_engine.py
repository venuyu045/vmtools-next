"""Bot engine resolution — shared by routers, TaskEngine, and pools.

An MCC bot is linked to an mcc_instances row (instances.bot_id → bots.bot_id),
and each instance declares its ``bot_engine`` ('mcc' | 'mineflayer').
These helpers centralize that lookup so every consumer routes to the same pool.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from vmtools_next.config import get_config


def resolve_bot_engine(bot_id: str, db: Session) -> str:
    """Return the bot_engine for a bot, defaulting to the configured engine.

    Falls back to the config default when the bot has no linked instance,
    instead of hardcoding 'mcc' (which would misroute mineflayer-bots that
    lack an instance row).
    """
    from vmtools_next.data.models.mcc_remote import MccInstanceModel

    inst = db.query(MccInstanceModel).filter(
        MccInstanceModel.bot_id == bot_id,
        MccInstanceModel.deleted_at.is_(None),
    ).first()
    if inst:
        engine = getattr(inst, "bot_engine", None)
        if engine:
            return engine
    mf_cfg = get_config().mineflayer
    default_engine = getattr(mf_cfg, "default_engine", "mcc") or "mcc"
    return default_engine if default_engine in ("mcc", "mineflayer") else "mcc"
