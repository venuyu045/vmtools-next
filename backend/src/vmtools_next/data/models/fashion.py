"""时装系统（VMFashion mod）ORM 模型。

五张表：

- ``fashion_identity``  已验证的 MC 身份（正版 / 皮肤站），可关联 vmtools 账号
- ``fashion_catalog``   时装目录（cosmetic 元数据，资产以 sha256 引用）
- ``fashion_loadout``   玩家穿戴配置，唯一约束 (identity_id, slot)
- ``fashion_asset``     资产文件（按 sha256 去重，落盘路径见 storage_path）
- ``fashion_wardrobe``  用户「我的衣柜」收藏，唯一约束 (user_id, cosmetic_id)

约定：``mc_uuid`` 统一存**带连字符的小写** UUID，读写入口都用
``core.fashion_auth.normalize_uuid`` 规范化，避免 ``AABB…`` / ``aabb…`` 两份数据。
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship

from vmtools_next.data.db import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class FashionIdentityModel(Base):
    """一条已验证的 Minecraft 身份（一个 MC UUID 一条）。"""

    __tablename__ = "fashion_identity"

    id = Column(String, primary_key=True)
    # 带连字符的小写 UUID（32 位无连字符入参会在入口规范化）
    mc_uuid = Column(String, nullable=False, unique=True, index=True)
    mc_name = Column(String, nullable=False, index=True)
    # mojang | yggdrasil
    auth_type = Column(String, nullable=False, default="mojang")
    # 皮肤站 base URL（正版为空串）
    auth_server = Column(String, nullable=False, default="")
    verified_at = Column(DateTime, nullable=True)
    # 关联的 vmtools 账号（设备码绑定后写入；可为 NULL）
    user_id = Column(String, ForeignKey("users.id"), nullable=True, index=True)
    created_at = Column(DateTime, default=_utcnow, nullable=False)
    last_seen_at = Column(DateTime, nullable=True)

    loadouts = relationship(
        "FashionLoadoutModel",
        back_populates="identity",
        cascade="all, delete-orphan",
    )


class FashionCatalogModel(Base):
    """时装目录条目（cosmetic）。

    资产不在库里内联，只用 ``sha256`` + ``bytes`` 指向 ``fashion_asset``
    或 ``asset_dir`` 下的静态文件；``asset_key`` 是 mod 侧请求资产时用的键。
    """

    __tablename__ = "fashion_catalog"

    cosmetic_id = Column(String, primary_key=True)
    pack_id = Column(String, nullable=False, default="", index=True)
    name = Column(String, nullable=False, default="")
    # cape | wings | hat | back | pet | aura | other
    category = Column(String, nullable=False, default="other", index=True)
    asset_key = Column(String, nullable=False, default="", index=True)
    sha256 = Column(String, nullable=False, default="")
    bytes = Column(Integer, nullable=False, default=0)
    enabled = Column(Boolean, nullable=False, default=True, index=True)
    sort_order = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, default=_utcnow, nullable=False)


class FashionLoadoutModel(Base):
    """玩家单个槽位的穿戴配置（(identity_id, slot) 唯一）。"""

    __tablename__ = "fashion_loadout"

    id = Column(String, primary_key=True)
    identity_id = Column(
        String, ForeignKey("fashion_identity.id"), nullable=False, index=True
    )
    # 槽位：cape | wings | hat | back | pet | aura | other
    slot = Column(String, nullable=False)
    cosmetic_id = Column(String, nullable=False)
    scale = Column(Float, nullable=False, default=1.0)
    updated_at = Column(DateTime, default=_utcnow, nullable=False)

    identity = relationship("FashionIdentityModel", back_populates="loadouts")

    __table_args__ = (
        UniqueConstraint("identity_id", "slot", name="uq_fashion_loadout_identity_slot"),
        Index("ix_fashion_loadout_identity_slot", "identity_id", "slot"),
    )


class FashionAssetModel(Base):
    """已上传的资产文件（同一 sha256 只落盘一份）。"""

    __tablename__ = "fashion_asset"

    id = Column(String, primary_key=True)
    pack_id = Column(String, nullable=False, default="", index=True)
    version = Column(String, nullable=False, default="1")
    filename = Column(String, nullable=False, default="")
    sha256 = Column(String, nullable=False, index=True)
    bytes = Column(Integer, nullable=False, default=0)
    # 相对 asset_dir 的落盘路径（禁止绝对路径 / ..）
    # index=True：`/assets/{key}` 的回退分支按 storage_path 精确查（见
    # core.fashion_service.asset_storage_path_exists）；无索引时会退化成全表扫描，
    # 4396 行资产下每个资产请求都全表扫一遍 —— 时装页一次拉几十个资产，
    # 直接把连接池打满（2026-11-01 事故 §六.106）。
    storage_path = Column(String, nullable=False, default="", index=True)
    created_at = Column(DateTime, default=_utcnow, nullable=False)


class FashionWardrobeModel(Base):
    """用户「我的衣柜」收藏（一件时装一条）。

    为什么按 ``user_id`` 而不是 ``identity_id``
    -------------------------------------------
    衣柜是**网站账号**的收藏夹（玩家在商店里「加入衣柜」），一个账号可能绑定多个
    MC 身份（正版 + 皮肤站），换身份登录时看到的是同一份衣柜才符合直觉；穿戴
    配置（``fashion_loadout``）才是身份维度的。所以这里外键指 ``users.id``。

    为什么保留 ``cosmetic_id`` 而不做外键
    ------------------------------------
    目录条目（``fashion_catalog``）随时可能被管理端删除/下架，但玩家已经收藏的
    记录不能跟着消失 —— 否则「删目录」会静默清空所有人的衣柜。目录查不到时由
    服务层把条目标成 ``missing`` 返回，玩家自己决定删不删。

    唯一约束 ``(user_id, cosmetic_id)``：重复「加入衣柜」是幂等的（不重复插入），
    同时兜住并发双击。
    """

    __tablename__ = "fashion_wardrobe"

    id = Column(String, primary_key=True)
    user_id = Column(String, ForeignKey("users.id"), nullable=False, index=True)
    cosmetic_id = Column(String, nullable=False, index=True)
    added_at = Column(DateTime, default=_utcnow, nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "user_id", "cosmetic_id", name="uq_fashion_wardrobe_user_cosmetic"
        ),
    )
