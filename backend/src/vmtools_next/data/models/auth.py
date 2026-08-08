"""Auth & organization ORM models (migrated from vmtools-backend).

Tables: users, organizations, warehouse_groups
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Column, String, Text, DateTime, ForeignKey, Index
from sqlalchemy.orm import relationship

from vmtools_next.data.db import Base


class OrganizationModel(Base):
    """An organization that owns warehouses and groups."""

    __tablename__ = "organizations"

    id = Column(String, primary_key=True)
    name = Column(String, nullable=False, unique=True)
    description = Column(Text, default="")
    created_by = Column(String, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    groups = relationship("WarehouseGroupModel", back_populates="organization", cascade="all, delete-orphan")
    members = relationship("UserModel", back_populates="organization")
    warehouses = relationship("WarehouseModel", backref="organization")


class WarehouseGroupModel(Base):
    """A named group of warehouses within an organization."""

    __tablename__ = "warehouse_groups"

    id = Column(String, primary_key=True)
    name = Column(String, nullable=False)
    organization_id = Column(String, ForeignKey("organizations.id"), nullable=False, index=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    organization = relationship("OrganizationModel", back_populates="groups")
    warehouses = relationship("WarehouseModel", backref="group")


class UserModel(Base):
    """A registered user account.

    Roles: site_admin, admin, user, guest
    Status: pending, approved, rejected, banned
    """

    __tablename__ = "users"

    id = Column(String, primary_key=True)
    game_id = Column(String, nullable=False, unique=True, index=True)
    password_hash = Column(String, nullable=False)
    display_name = Column(String, default="")
    role = Column(String, default="guest", nullable=False)
    organization_id = Column(String, ForeignKey("organizations.id"), nullable=True, index=True)
    status = Column(String, default="pending", nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    approved_at = Column(DateTime, nullable=True)
    approved_by = Column(String, nullable=True)
    # QQ 互联绑定：qq_openid 唯一（一个 QQ 只能注册一个账号）；qq_nickname 供展示
    qq_openid = Column(String, nullable=True, unique=True, index=True)
    qq_nickname = Column(String, nullable=True)
    # 上次上线时间 = 最近一次访问网页/登录的时间（成员管理「上次上线」列）
    last_seen_at = Column(DateTime, nullable=True)

    organization = relationship("OrganizationModel", back_populates="members")
