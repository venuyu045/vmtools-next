"""Site-admin user management API (member management).

Allows the site_admin to list all registered users, approve/reject pending
registration requests, and edit every member's status / role.

Prefix: /api/admin/users  (site_admin only)
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from vmtools_next.api.deps import get_db, require_site_admin
from vmtools_next.data.models.auth import UserModel

router = APIRouter(prefix="/api/admin/users", tags=["admin"])

VALID_STATUS = {"pending", "approved", "rejected", "banned"}
# 权限组重构后：站点管理员 / 管理员 / 用户 / 访客（org_member、org_admin 已废弃）
VALID_ROLES = {"site_admin", "admin", "user", "guest"}


class UserUpdateRequest(BaseModel):
    status: str | None = None
    role: str | None = None


class UserOut(BaseModel):
    id: str
    game_id: str
    display_name: str
    role: str
    status: str
    organization_id: str | None = None
    created_at: datetime | None = None
    approved_at: datetime | None = None
    last_seen_at: datetime | None = None  # 上次上线时间（最近一次访问网页/登录）


def _serialize(u: UserModel) -> UserOut:
    return UserOut(
        id=u.id,
        game_id=u.game_id,
        display_name=u.display_name,
        role=u.role,
        status=u.status,
        organization_id=u.organization_id,
        created_at=u.created_at,
        approved_at=u.approved_at,
        last_seen_at=u.last_seen_at,
    )


@router.get("", response_model=list[UserOut])
def list_users(
    status: str | None = None,
    db: Session = Depends(get_db),
    admin: UserModel = Depends(require_site_admin),
):
    """List all registered users, optionally filtered by status."""
    q = db.query(UserModel)
    if status:
        if status not in VALID_STATUS:
            raise HTTPException(400, f"Invalid status filter: {status}")
        q = q.filter(UserModel.status == status)
    users = q.order_by(UserModel.created_at.desc()).all()
    return [_serialize(u) for u in users]


@router.patch("/{user_id}", response_model=UserOut)
def update_user(
    user_id: str,
    data: UserUpdateRequest,
    db: Session = Depends(get_db),
    admin: UserModel = Depends(require_site_admin),
):
    """Approve/reject a registration, ban a member, or change a role."""
    user = db.query(UserModel).filter(UserModel.id == user_id).first()
    if not user:
        raise HTTPException(404, "User not found")

    if not data.status and not data.role:
        raise HTTPException(400, "Nothing to update")

    if data.status is not None:
        if data.status not in VALID_STATUS:
            raise HTTPException(400, f"Invalid status: {data.status}")
        user.status = data.status
        if data.status == "approved" and not user.approved_at:
            user.approved_at = datetime.now(timezone.utc)
            user.approved_by = admin.id
        elif data.status == "pending":
            user.approved_at = None
            user.approved_by = None

    if data.role is not None:
        if data.role not in VALID_ROLES:
            raise HTTPException(400, f"Invalid role: {data.role}")
        # Never demote the last site_admin — that would lock everyone out.
        if user.role == "site_admin" and data.role != "site_admin":
            site_admin_count = (
                db.query(UserModel).filter(UserModel.role == "site_admin").count()
            )
            if site_admin_count <= 1:
                raise HTTPException(400, "Cannot demote the last site admin")
        user.role = data.role

    db.commit()
    db.refresh(user)
    return _serialize(user)


@router.delete("/{user_id}")
def delete_user(
    user_id: str,
    db: Session = Depends(get_db),
    admin: UserModel = Depends(require_site_admin),
):
    """删除成员（仅 site_admin）。

    保护：不能删除最后一个 site_admin（避免全员锁死）；
    不能删除自己（防止管理员误删当前会话）。
    """
    user = db.query(UserModel).filter(UserModel.id == user_id).first()
    if not user:
        raise HTTPException(404, "User not found")

    if user.id == admin.id:
        raise HTTPException(400, "不能删除当前登录的管理员账号")

    if user.role == "site_admin":
        site_admin_count = (
            db.query(UserModel).filter(UserModel.role == "site_admin").count()
        )
        if site_admin_count <= 1:
            raise HTTPException(400, "不能删除最后一个站点管理员")

    db.delete(user)
    db.commit()
    return {"status": "deleted", "user_id": user_id, "game_id": user.game_id}
