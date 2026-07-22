"""Player tracking config stored in DB (not config.yaml) to survive git reset --hard."""
from __future__ import annotations

from sqlalchemy import Column, String, Text, Integer
from sqlalchemy.orm import declarative_base

# Use same Base
from vmtools_next.data.db import Base


class PlayerTrackingOwnerModel(Base):
    __tablename__ = "player_tracking_owners"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(128), nullable=False, unique=True, index=True)
    qq_openid = Column(String(256), default="")
    track_players_json = Column(Text, default="[]")  # JSON list of player names
