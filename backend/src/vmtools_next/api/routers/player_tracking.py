"""Player tracking config management API.

Owner tracking data is stored in the database (player_tracking_owners table),
NOT in config.yaml, to survive git operations and cross-conversation syncs.
"""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from vmtools_next.config import get_config, reload_config
from vmtools_next.data.db import get_db, get_session_factory
from vmtools_next.data.models.player_tracking import PlayerTrackingOwnerModel
from vmtools_next.data.models.auth import UserModel
from vmtools_next.api.deps import get_current_user
from vmtools_next.infra.logging import get_logger

logger = get_logger("player_tracking")

router = APIRouter(prefix="/api/player-tracking", tags=["player-tracking"])


class TrackOwnerOut(BaseModel):
    name: str
    qq_openid: str = ""
    track_players: list[str] = []


class PlayerTrackingOut(BaseModel):
    enabled: bool
    sentinel_instance: str
    owners: list[TrackOwnerOut]


# ── In-memory cache for config.runtime access ──
# The bluemap_monitor and mcc_process_manager read player_tracking config
# at runtime. We sync DB → config on every write.
def _sync_db_to_config() -> None:
    """Sync owners from DB into the live config, so runtime code sees them."""
    Session = get_session_factory()
    db = Session()
    try:
        from vmtools_next.config import get_config as _cfg_get, TrackOwner
        owners_db = db.query(PlayerTrackingOwnerModel).all()
        owners = [
            TrackOwner(
                name=o.name,
                qq_openid=o.qq_openid,
                track_players=json.loads(o.track_players_json),
            )
            for o in owners_db
        ]
        # Mutate cached config in-place (don't clear cache)
        _cfg_get().player_tracking.owners = owners
    finally:
        db.close()


# ── Startup: migrate existing data from config.yaml → DB ──

def _migrate_from_config(db: Session) -> int:
    """One-time migration: copy owners from config.yaml into DB table.
    Returns count of migrated owners.
    """
    try:
        cfg = get_config().player_tracking
        owners = cfg.owners
        if not owners:
            return 0

        migrated = 0
        for o in owners:
            existing = db.query(PlayerTrackingOwnerModel).filter(
                PlayerTrackingOwnerModel.name == o.name
            ).first()
            if existing:
                existing.qq_openid = o.qq_openid
                existing.track_players_json = json.dumps(list(o.track_players), ensure_ascii=False)
            else:
                db.add(PlayerTrackingOwnerModel(
                    name=o.name,
                    qq_openid=o.qq_openid,
                    track_players_json=json.dumps(list(o.track_players), ensure_ascii=False),
                ))
                migrated += 1
        db.commit()
        if migrated:
            logger.info("Migrated {} player tracking owners from config.yaml to DB", migrated)
        return migrated
    except Exception:
        db.rollback()
        return 0


# ── API Endpoints ──

@router.get("", response_model=PlayerTrackingOut)
def get_player_tracking(
    user: UserModel = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    cfg = get_config().player_tracking

    # Auto-migrate from config.yaml on first access
    _migrate_from_config(db)

    owners_db = db.query(PlayerTrackingOwnerModel).all()
    owners_out = [
        TrackOwnerOut(
            name=o.name,
            qq_openid=o.qq_openid,
            track_players=json.loads(o.track_players_json),
        )
        for o in owners_db
    ]

    return PlayerTrackingOut(
        enabled=cfg.enabled,
        sentinel_instance=cfg.sentinel_instance,
        owners=owners_out,
    )


@router.put("", response_model=PlayerTrackingOut)
def update_player_tracking(
    data: PlayerTrackingOut,
    user: UserModel = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    # Update config.yaml for enabled/sentinel_instance (these are server settings)
    from vmtools_next.config import _find_config_dir
    from pathlib import Path
    import yaml
    config_path = Path(_find_config_dir()) / "config.yaml"
    with open(config_path, "r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}
    raw.setdefault("player_tracking", {})["enabled"] = data.enabled
    raw["player_tracking"]["sentinel_instance"] = data.sentinel_instance
    with open(config_path, "w", encoding="utf-8") as fh:
        yaml.safe_dump(raw, fh, allow_unicode=True, default_flow_style=False, sort_keys=False)
    reload_config()

    # Update owners in DB
    existing_names = {o.name for o in db.query(PlayerTrackingOwnerModel).all()}
    incoming_names = set()

    for o_in in data.owners:
        incoming_names.add(o_in.name)
        existing = db.query(PlayerTrackingOwnerModel).filter(
            PlayerTrackingOwnerModel.name == o_in.name
        ).first()
        if existing:
            existing.qq_openid = o_in.qq_openid
            existing.track_players_json = json.dumps(o_in.track_players, ensure_ascii=False)
        else:
            db.add(PlayerTrackingOwnerModel(
                name=o_in.name,
                qq_openid=o_in.qq_openid,
                track_players_json=json.dumps(o_in.track_players, ensure_ascii=False),
            ))

    # Remove owners no longer in the list
    removed = existing_names - incoming_names
    if removed:
        db.query(PlayerTrackingOwnerModel).filter(
            PlayerTrackingOwnerModel.name.in_(removed)
        ).delete(synchronize_session=False)

    db.commit()

    # Sync into runtime config
    _sync_db_to_config()

    return data
