"""Player tracking config management API."""
from __future__ import annotations

from pathlib import Path

import yaml
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from vmtools_next.config import _find_config_dir, get_config, reload_config
from vmtools_next.data.models.auth import UserModel
from vmtools_next.deps import get_current_user

router = APIRouter(prefix="/api/player-tracking", tags=["player-tracking"])


class TrackedPlayerOut(BaseModel):
    name: str
    qq_openid: str = ""


class PlayerTrackingOut(BaseModel):
    enabled: bool
    sentinel_instance: str
    players: list[TrackedPlayerOut]


@router.get("", response_model=PlayerTrackingOut)
def get_player_tracking(user: UserModel = Depends(get_current_user)):
    cfg = get_config().player_tracking
    return PlayerTrackingOut(
        enabled=cfg.enabled,
        sentinel_instance=cfg.sentinel_instance,
        players=[TrackedPlayerOut(name=p.name, qq_openid=p.qq_openid) for p in cfg.players],
    )


@router.put("", response_model=PlayerTrackingOut)
def update_player_tracking(
    data: PlayerTrackingOut,
    user: UserModel = Depends(get_current_user),
):
    config_dir = _find_config_dir()
    config_path = Path(config_dir) / "config.yaml"
    with open(config_path, "r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}

    raw.setdefault("player_tracking", {})
    raw["player_tracking"]["enabled"] = data.enabled
    raw["player_tracking"]["sentinel_instance"] = data.sentinel_instance
    raw["player_tracking"]["players"] = [
        {"name": p.name, "qq_openid": p.qq_openid} for p in data.players
    ]

    with open(config_path, "w", encoding="utf-8") as fh:
        yaml.safe_dump(raw, fh, allow_unicode=True, default_flow_style=False, sort_keys=False)

    reload_config()
    return data
