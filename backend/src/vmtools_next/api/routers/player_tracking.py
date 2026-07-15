"""Player tracking config management API."""
from __future__ import annotations

from pathlib import Path

import yaml
from fastapi import APIRouter, Depends
from pydantic import BaseModel

from vmtools_next.config import _find_config_dir, get_config, reload_config
from vmtools_next.data.models.auth import UserModel
from vmtools_next.api.deps import get_current_user

router = APIRouter(prefix="/api/player-tracking", tags=["player-tracking"])


class TrackOwnerOut(BaseModel):
    name: str
    qq_openid: str = ""
    track_players: list[str] = []


class PlayerTrackingOut(BaseModel):
    enabled: bool
    sentinel_instance: str
    owners: list[TrackOwnerOut]


@router.get("", response_model=PlayerTrackingOut)
def get_player_tracking(user: UserModel = Depends(get_current_user)):
    cfg = get_config().player_tracking
    return PlayerTrackingOut(
        enabled=cfg.enabled,
        sentinel_instance=cfg.sentinel_instance,
        owners=[
            TrackOwnerOut(
                name=o.name,
                qq_openid=o.qq_openid,
                track_players=list(o.track_players),
            )
            for o in cfg.owners
        ],
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

    raw["player_tracking"] = {
        "enabled": data.enabled,
        "sentinel_instance": data.sentinel_instance,
        "owners": [
            {"name": o.name, "qq_openid": o.qq_openid, "track_players": o.track_players}
            for o in data.owners
        ],
    }

    with open(config_path, "w", encoding="utf-8") as fh:
        yaml.safe_dump(raw, fh, allow_unicode=True, default_flow_style=False, sort_keys=False)

    reload_config()
    return data
