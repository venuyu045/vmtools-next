"""理想乡组织官网 API。

公开读接口（访客免登录可浏览官网）：
    GET  /api/lixiangxiang/info         组织介绍（intro/history/slogan/settings）
    GET  /api/lixiangxiang/members      成员列表
    GET  /api/lixiangxiang/bases        基地展示列表
    GET  /api/lixiangxiang/categories   相册分类列表
    GET  /api/lixiangxiang/images       相册图片（?category_id= 可选过滤）

管理接口（仅 admin / site_admin，非管理员 403）：
    PUT  /api/lixiangxiang/info         更新组织介绍（部分键更新）
    POST /api/lixiangxiang/members      新增成员
    PUT  /api/lixiangxiang/members/{id} 更新成员
    DELETE /api/lixiangxiang/members/{id} 删除成员
    POST /api/lixiangxiang/bases        新增基地
    PUT  /api/lixiangxiang/bases/{id}   更新基地
    DELETE /api/lixiangxiang/bases/{id} 删除基地
    POST /api/lixiangxiang/categories   新增相册分类
    PUT  /api/lixiangxiang/categories/{id} 更新分类
    DELETE /api/lixiangxiang/categories/{id} 删除分类
    POST /api/lixiangxiang/images       新增相册图片记录
    PUT  /api/lixiangxiang/images/{id}  更新图片（标题/分类/描述）
    DELETE /api/lixiangxiang/images/{id} 删除图片
    POST /api/lixiangxiang/upload       通用图片上传（成员头像/基地图/相册图）

上传图片保存到 backend/static/lixiangxiang/uploads/，经 /static/lixiangxiang/... 访问
（FastAPI 已挂载 /static，无需重启）。
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from pydantic import BaseModel
from sqlalchemy.orm import Session

from vmtools_next.api.deps import get_db, require_admin
from vmtools_next.data.models.lixiangxiang import (
    OrganizationInfoModel, MemberModel, LxBaseModel,
    GalleryCategoryModel, GalleryImageModel,
)
from vmtools_next.infra.logging import get_logger

logger = get_logger("api.lixiangxiang")
router = APIRouter(prefix="/api/lixiangxiang", tags=["lixiangxiang"])

# backend/static/lixiangxiang（router 文件上溯 5 级到 backend，再进 static）
_STATIC_DIR = Path(__file__).resolve().parent.parent.parent.parent.parent / "static"
_LX_DIR = _STATIC_DIR / "lixiangxiang"
_UPLOAD_DIR = _LX_DIR / "uploads"

_ALLOWED_EXT = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg"}
_MAX_SIZE = 10 * 1024 * 1024  # 10MB


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: Optional[datetime]) -> Optional[str]:
    return dt.isoformat() if dt else None


# ──────────────────────────────────────────────
# Pydantic schemas
# ──────────────────────────────────────────────

class InfoUpdate(BaseModel):
    """组织介绍更新：部分键更新（如 {"intro": "...", "slogan": "..."}）。"""
    intro: Optional[str] = None
    history: Optional[str] = None
    slogan: Optional[str] = None
    settings: Optional[str] = None


class MemberCreate(BaseModel):
    game_id: str
    nickname: str = ""
    title: str = ""
    joined_at: str = ""
    specialty: str = ""
    avatar_path: str = ""
    bio: str = ""
    sort_order: int = 0


class MemberUpdate(BaseModel):
    game_id: Optional[str] = None
    nickname: Optional[str] = None
    title: Optional[str] = None
    joined_at: Optional[str] = None
    specialty: Optional[str] = None
    avatar_path: Optional[str] = None
    bio: Optional[str] = None
    sort_order: Optional[int] = None


class BaseCreate(BaseModel):
    name: str
    description: str = ""
    image_path: str = ""
    coordinates: str = ""
    sort_order: int = 0


class BaseUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    image_path: Optional[str] = None
    coordinates: Optional[str] = None
    sort_order: Optional[int] = None


class CategoryCreate(BaseModel):
    name: str
    sort_order: int = 0


class CategoryUpdate(BaseModel):
    name: Optional[str] = None
    sort_order: Optional[int] = None


class ImageCreate(BaseModel):
    image_path: str
    category_id: Optional[str] = None
    title: str = ""
    description: str = ""


class ImageUpdate(BaseModel):
    image_path: Optional[str] = None
    category_id: Optional[str] = None
    title: Optional[str] = None
    description: Optional[str] = None


# ──────────────────────────────────────────────
# 公开读接口（访客免登录）
# ──────────────────────────────────────────────

@router.get("/info")
def get_info(db: Session = Depends(get_db)):
    """组织介绍：返回全部键值对 + 解析后的 settings 对象。"""
    rows = db.query(OrganizationInfoModel).all()
    data = {r.key: r.value for r in rows}
    settings = {}
    if data.get("settings"):
        try:
            settings = json.loads(data["settings"])
        except Exception:
            settings = {}
    return {
        "intro": data.get("intro", ""),
        "history": data.get("history", ""),
        "slogan": data.get("slogan", ""),
        "settings": settings,
    }


def _member_dict(m: MemberModel) -> dict:
    return {
        "id": m.id,
        "game_id": m.game_id,
        "nickname": m.nickname,
        "title": m.title,
        "joined_at": m.joined_at,
        "specialty": m.specialty,
        "avatar_path": m.avatar_path,
        "bio": m.bio,
        "sort_order": m.sort_order,
    }


@router.get("/members")
def list_members(db: Session = Depends(get_db)):
    """成员列表（按 sort_order 升序）。"""
    rows = db.query(MemberModel).order_by(MemberModel.sort_order.asc(), MemberModel.created_at.asc()).all()
    return [_member_dict(m) for m in rows]


def _base_dict(b: LxBaseModel) -> dict:
    return {
        "id": b.id,
        "name": b.name,
        "description": b.description,
        "image_path": b.image_path,
        "coordinates": b.coordinates,
        "sort_order": b.sort_order,
    }


@router.get("/bases")
def list_bases(db: Session = Depends(get_db)):
    """基地展示列表（按 sort_order 升序）。"""
    rows = db.query(LxBaseModel).order_by(LxBaseModel.sort_order.asc(), LxBaseModel.created_at.asc()).all()
    return [_base_dict(b) for b in rows]


@router.get("/categories")
def list_categories(db: Session = Depends(get_db)):
    """相册分类列表（按 sort_order 升序，附带每类图片数）。"""
    rows = db.query(GalleryCategoryModel).order_by(GalleryCategoryModel.sort_order.asc()).all()
    counts = dict(
        db.query(GalleryImageModel.category_id, GalleryImageModel.id)
        .group_by(GalleryImageModel.category_id)
        .all()
    )
    result = []
    for c in rows:
        img_count = sum(1 for cid in counts if cid == c.id)
        result.append({"id": c.id, "name": c.name, "sort_order": c.sort_order, "image_count": img_count})
    return result


@router.get("/images")
def list_images(category_id: Optional[str] = None, db: Session = Depends(get_db)):
    """相册图片（按上传时间倒序；?category_id= 可选过滤）。"""
    q = db.query(GalleryImageModel)
    if category_id:
        q = q.filter(GalleryImageModel.category_id == category_id)
    rows = q.order_by(GalleryImageModel.uploaded_at.desc()).all()
    return [
        {
            "id": g.id,
            "category_id": g.category_id,
            "image_path": g.image_path,
            "title": g.title,
            "description": g.description,
            "uploaded_at": _iso(g.uploaded_at),
        }
        for g in rows
    ]


# ──────────────────────────────────────────────
# 管理接口（仅 admin / site_admin）
# ──────────────────────────────────────────────

@router.put("/info")
def update_info(body: InfoUpdate, db: Session = Depends(get_db), user=Depends(require_admin)):
    """更新组织介绍（部分键更新；settings 存 JSON 字符串）。"""
    updates = body.model_dump(exclude_none=True)
    if not updates:
        raise HTTPException(status_code=400, detail="没有需要更新的字段")
    now = _now()
    for key, value in updates.items():
        row = db.query(OrganizationInfoModel).filter(OrganizationInfoModel.key == key).first()
        if row is None:
            row = OrganizationInfoModel(key=key, value="", updated_at=now)
            db.add(row)
        row.value = value
        row.updated_at = now
    db.commit()
    logger.info("Lixiangxiang info updated by {}: keys={}", user.game_id, list(updates.keys()))
    return get_info(db)


@router.post("/members", status_code=201)
def create_member(body: MemberCreate, db: Session = Depends(get_db), user=Depends(require_admin)):
    if not body.game_id.strip():
        raise HTTPException(status_code=400, detail="游戏 ID 不能为空")
    m = MemberModel(
        id=uuid.uuid4().hex,
        game_id=body.game_id.strip(),
        nickname=body.nickname,
        title=body.title,
        joined_at=body.joined_at,
        specialty=body.specialty,
        avatar_path=body.avatar_path,
        bio=body.bio,
        sort_order=body.sort_order,
        created_at=_now(),
        updated_at=_now(),
    )
    db.add(m)
    db.commit()
    logger.info("Lixiangxiang member created by {}: {}", user.game_id, m.game_id)
    return _member_dict(m)


@router.put("/members/{member_id}")
def update_member(member_id: str, body: MemberUpdate, db: Session = Depends(get_db), user=Depends(require_admin)):
    m = db.query(MemberModel).filter(MemberModel.id == member_id).first()
    if not m:
        raise HTTPException(status_code=404, detail="成员不存在")
    data = body.model_dump(exclude_none=True)
    if "game_id" in data and not str(data["game_id"]).strip():
        raise HTTPException(status_code=400, detail="游戏 ID 不能为空")
    for key, value in data.items():
        setattr(m, key, value.strip() if isinstance(value, str) else value)
    m.updated_at = _now()
    db.commit()
    return _member_dict(m)


@router.delete("/members/{member_id}", status_code=204)
def delete_member(member_id: str, db: Session = Depends(get_db), user=Depends(require_admin)):
    m = db.query(MemberModel).filter(MemberModel.id == member_id).first()
    if not m:
        raise HTTPException(status_code=404, detail="成员不存在")
    db.delete(m)
    db.commit()
    logger.info("Lixiangxiang member deleted by {}: {}", user.game_id, member_id)


@router.post("/bases", status_code=201)
def create_base(body: BaseCreate, db: Session = Depends(get_db), user=Depends(require_admin)):
    if not body.name.strip():
        raise HTTPException(status_code=400, detail="基地名称不能为空")
    b = LxBaseModel(
        id=uuid.uuid4().hex,
        name=body.name.strip(),
        description=body.description,
        image_path=body.image_path,
        coordinates=body.coordinates,
        sort_order=body.sort_order,
        created_at=_now(),
        updated_at=_now(),
    )
    db.add(b)
    db.commit()
    return _base_dict(b)


@router.put("/bases/{base_id}")
def update_base(base_id: str, body: BaseUpdate, db: Session = Depends(get_db), user=Depends(require_admin)):
    b = db.query(LxBaseModel).filter(LxBaseModel.id == base_id).first()
    if not b:
        raise HTTPException(status_code=404, detail="基地不存在")
    data = body.model_dump(exclude_none=True)
    if "name" in data and not str(data["name"]).strip():
        raise HTTPException(status_code=400, detail="基地名称不能为空")
    for key, value in data.items():
        setattr(b, key, value.strip() if isinstance(value, str) else value)
    b.updated_at = _now()
    db.commit()
    return _base_dict(b)


@router.delete("/bases/{base_id}", status_code=204)
def delete_base(base_id: str, db: Session = Depends(get_db), user=Depends(require_admin)):
    b = db.query(LxBaseModel).filter(LxBaseModel.id == base_id).first()
    if not b:
        raise HTTPException(status_code=404, detail="基地不存在")
    db.delete(b)
    db.commit()
    logger.info("Lixiangxiang base deleted by {}: {}", user.game_id, base_id)


@router.post("/categories", status_code=201)
def create_category(body: CategoryCreate, db: Session = Depends(get_db), user=Depends(require_admin)):
    if not body.name.strip():
        raise HTTPException(status_code=400, detail="分类名不能为空")
    c = GalleryCategoryModel(id=uuid.uuid4().hex, name=body.name.strip(), sort_order=body.sort_order, created_at=_now())
    db.add(c)
    db.commit()
    return {"id": c.id, "name": c.name, "sort_order": c.sort_order, "image_count": 0}


@router.put("/categories/{category_id}")
def update_category(category_id: str, body: CategoryUpdate, db: Session = Depends(get_db), user=Depends(require_admin)):
    c = db.query(GalleryCategoryModel).filter(GalleryCategoryModel.id == category_id).first()
    if not c:
        raise HTTPException(status_code=404, detail="分类不存在")
    data = body.model_dump(exclude_none=True)
    if "name" in data and not str(data["name"]).strip():
        raise HTTPException(status_code=400, detail="分类名不能为空")
    for key, value in data.items():
        setattr(c, key, value.strip() if isinstance(value, str) else value)
    db.commit()
    return {"id": c.id, "name": c.name, "sort_order": c.sort_order}


@router.delete("/categories/{category_id}", status_code=204)
def delete_category(category_id: str, db: Session = Depends(get_db), user=Depends(require_admin)):
    c = db.query(GalleryCategoryModel).filter(GalleryCategoryModel.id == category_id).first()
    if not c:
        raise HTTPException(status_code=404, detail="分类不存在")
    # 分类下的图片保留但置为未分类（不级联删图，避免误删）
    db.query(GalleryImageModel).filter(GalleryImageModel.category_id == category_id).update(
        {GalleryImageModel.category_id: None}
    )
    db.delete(c)
    db.commit()
    logger.info("Lixiangxiang category deleted by {}: {}", user.game_id, category_id)


@router.post("/images", status_code=201)
def create_image(body: ImageCreate, db: Session = Depends(get_db), user=Depends(require_admin)):
    if not body.image_path.strip():
        raise HTTPException(status_code=400, detail="图片路径不能为空")
    g = GalleryImageModel(
        id=uuid.uuid4().hex,
        category_id=body.category_id,
        image_path=body.image_path.strip(),
        title=body.title,
        description=body.description,
        uploaded_at=_now(),
    )
    db.add(g)
    db.commit()
    return {"id": g.id, "category_id": g.category_id, "image_path": g.image_path,
            "title": g.title, "description": g.description, "uploaded_at": _iso(g.uploaded_at)}


@router.put("/images/{image_id}")
def update_image(image_id: str, body: ImageUpdate, db: Session = Depends(get_db), user=Depends(require_admin)):
    g = db.query(GalleryImageModel).filter(GalleryImageModel.id == image_id).first()
    if not g:
        raise HTTPException(status_code=404, detail="图片不存在")
    data = body.model_dump(exclude_none=True)
    for key, value in data.items():
        setattr(g, key, value.strip() if isinstance(value, str) else value)
    db.commit()
    return {"id": g.id, "category_id": g.category_id, "image_path": g.image_path,
            "title": g.title, "description": g.description, "uploaded_at": _iso(g.uploaded_at)}


@router.delete("/images/{image_id}", status_code=204)
def delete_image(image_id: str, db: Session = Depends(get_db), user=Depends(require_admin)):
    g = db.query(GalleryImageModel).filter(GalleryImageModel.id == image_id).first()
    if not g:
        raise HTTPException(status_code=404, detail="图片不存在")
    _try_remove_file(g.image_path)
    db.delete(g)
    db.commit()
    logger.info("Lixiangxiang image deleted by {}: {}", user.game_id, image_id)


# ──────────────────────────────────────────────
# 通用图片上传
# ──────────────────────────────────────────────

def _try_remove_file(url_path: str) -> None:
    """删除上传目录内的文件（仅限 /static/lixiangxiang/uploads/ 下，防路径穿越）。"""
    if not url_path.startswith("/static/lixiangxiang/"):
        return
    rel = url_path.removeprefix("/static/lixiangxiang/")
    target = (_LX_DIR / rel).resolve()
    # 只允许删除 uploads 目录内的文件
    if target.is_file() and target.parent == _UPLOAD_DIR.resolve():
        try:
            target.unlink()
        except Exception as e:
            logger.warning("Failed to remove old file {}: {}", target, e)


@router.post("/upload")
async def upload_image(file: UploadFile = File(...), user=Depends(require_admin)):
    """通用图片上传：返回可访问的 URL 路径（/static/lixiangxiang/uploads/xxx.png）。"""
    _UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    ext = Path(file.filename or "").suffix.lower()
    if ext not in _ALLOWED_EXT:
        raise HTTPException(status_code=400, detail=f"不支持的图片格式：{ext or '未知'}（仅 png/jpg/jpeg/gif/webp/svg）")
    content = await file.read()
    if len(content) > _MAX_SIZE:
        raise HTTPException(status_code=400, detail="图片过大（上限 10MB）")
    if len(content) == 0:
        raise HTTPException(status_code=400, detail="空文件")
    # 校验 PNG/JPEG magic（防伪装文件）
    if ext in (".png",) and not content.startswith(b"\x89PNG"):
        raise HTTPException(status_code=400, detail="不是有效的 PNG 文件")
    if ext in (".jpg", ".jpeg") and not content.startswith(b"\xff\xd8"):
        raise HTTPException(status_code=400, detail="不是有效的 JPEG 文件")
    if ext in (".gif",) and not content.startswith(b"GIF8"):
        raise HTTPException(status_code=400, detail="不是有效的 GIF 文件")

    filename = f"{uuid.uuid4().hex}{ext}"
    dest = _UPLOAD_DIR / filename
    dest.write_bytes(content)
    logger.info("Lixiangxiang upload by {}: {} ({} bytes)", user.game_id, filename, len(content))
    return {"url": f"/static/lixiangxiang/uploads/{filename}"}