"""理想乡组织官网 ORM 模型（NEW）。

表：
- organization_info  组织介绍（键值对：intro / history / slogan / settings）
- members            成员信息（游戏ID、职位、加入时间、擅长领域、头像、排序）
- bases              地图基地展示（名称、介绍、截图、坐标、排序）
- gallery_categories 截图相册分类（名称、排序）
- gallery_images     截图相册图片（分类外键、图片路径、标题、描述、上传时间）

风格与现有模型保持一致：String 主键 + UTC DateTime；迁移走
Base.metadata.create_all（新表自动建）+ _run_lightweight_migrations（幂等加列）。
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Column, String, Integer, Text, DateTime

from vmtools_next.data.db import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class OrganizationInfoModel(Base):
    """组织介绍键值表：key ∈ {intro, history, slogan, settings}"""

    __tablename__ = "organization_info"

    key = Column(String, primary_key=True)
    value = Column(Text, nullable=False, default="")
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow, nullable=False)


class MemberModel(Base):
    """理想乡成员信息。"""

    __tablename__ = "members"

    id = Column(String, primary_key=True)
    game_id = Column(String, nullable=False)          # 游戏 ID
    nickname = Column(String, default="")             # 展示名（游戏内常用称呼）
    title = Column(String, default="")                # 职位 / 称号
    joined_at = Column(String, default="")            # 加入时间（YYYY-MM 或自由文本）
    specialty = Column(String, default="")            # 擅长领域
    avatar_path = Column(String, default="")          # 头像路径（/static/lixiangxiang/... 或外链）
    bio = Column(Text, default="")                    # 简介
    sort_order = Column(Integer, default=0, nullable=False)
    created_at = Column(DateTime, default=_utcnow, nullable=False)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow, nullable=False)


class LxBaseModel(Base):
    """地图基地展示。表名 bases（与 SQL 关键字无冲突）。"""

    __tablename__ = "bases"

    id = Column(String, primary_key=True)
    name = Column(String, nullable=False)             # 基地名称
    description = Column(Text, default="")            # 文字介绍
    image_path = Column(String, default="")           # 截图路径
    coordinates = Column(String, default="")          # 坐标（如 "-2673, 57, 9627"）
    sort_order = Column(Integer, default=0, nullable=False)
    created_at = Column(DateTime, default=_utcnow, nullable=False)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow, nullable=False)


class GalleryCategoryModel(Base):
    """截图相册分类。"""

    __tablename__ = "gallery_categories"

    id = Column(String, primary_key=True)
    name = Column(String, nullable=False)             # 分类名（如「建筑风景」「活动记录」）
    sort_order = Column(Integer, default=0, nullable=False)
    created_at = Column(DateTime, default=_utcnow, nullable=False)


class GalleryImageModel(Base):
    """截图相册图片。"""

    __tablename__ = "gallery_images"

    id = Column(String, primary_key=True)
    category_id = Column(String, nullable=True)       # FK → gallery_categories.id（可空=未分类）
    image_path = Column(String, nullable=False)       # 图片路径（/static/lixiangxiang/...）
    title = Column(String, default="")                # 标题
    description = Column(Text, default="")            # 描述
    uploaded_at = Column(DateTime, default=_utcnow, nullable=False)
