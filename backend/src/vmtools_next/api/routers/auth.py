"""Authentication API routes."""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from vmtools_next.api.deps import get_db, get_current_user
from vmtools_next.config import get_config
from vmtools_next.data.models.auth import UserModel

router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginRequest(BaseModel):
    game_id: str
    password: str


class LoginResponse(BaseModel):
    token: str
    user_id: str
    game_id: str
    role: str


class RegisterRequest(BaseModel):
    game_id: str
    password: str
    display_name: str = ""


class ChangePasswordRequest(BaseModel):
    old_password: str
    new_password: str


@router.post("/login", response_model=LoginResponse)
def login(data: LoginRequest, db: Session = Depends(get_db)):
    """Login with game_id and password."""
    user = db.query(UserModel).filter(UserModel.game_id == data.game_id).first()
    if not user:
        raise HTTPException(401, "Invalid credentials")

    if not bcrypt.checkpw(data.password.encode("utf-8"), user.password_hash.encode("utf-8")):
        raise HTTPException(401, "Invalid credentials")

    if user.status != "approved":
        raise HTTPException(403, "User not approved")

    config = get_config()
    token = jwt.encode(
        {"sub": user.id, "exp": datetime.now(timezone.utc) + timedelta(hours=24)},
        config.server.secret_key,
        algorithm=config.server.jwt_algorithm,
    )

    return LoginResponse(token=token, user_id=user.id, game_id=user.game_id, role=user.role)


@router.post("/register")
def register(data: RegisterRequest, db: Session = Depends(get_db)):
    """Register a new user (pending approval)."""
    existing = db.query(UserModel).filter(UserModel.game_id == data.game_id).first()
    if existing:
        raise HTTPException(400, "Game ID already registered")

    password_hash = bcrypt.hashpw(data.password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
    user = UserModel(
        id=str(uuid.uuid4()),
        game_id=data.game_id,
        password_hash=password_hash,
        display_name=data.display_name or data.game_id,
        role="user",
        status="pending",
    )
    db.add(user)
    db.commit()

    return {"status": "pending", "message": "Registration submitted, awaiting approval"}


@router.get("/me")
def get_me(user=Depends(get_current_user)):
    """Get current user info."""
    return {
        "id": user.id,
        "game_id": user.game_id,
        "display_name": user.display_name,
        "role": user.role,
        "status": user.status,
        "organization_id": user.organization_id,
    }


@router.post("/change-password")
def change_password(
    data: ChangePasswordRequest,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    """Change the current user's password (requires old password)."""
    if not data.old_password or not data.new_password:
        raise HTTPException(400, "旧密码与新密码不能为空")

    if not bcrypt.checkpw(data.old_password.encode("utf-8"), user.password_hash.encode("utf-8")):
        raise HTTPException(401, "旧密码不正确")

    if len(data.new_password) < 6:
        raise HTTPException(400, "新密码长度不能少于 6 位")

    user.password_hash = bcrypt.hashpw(
        data.new_password.encode("utf-8"), bcrypt.gensalt()
    ).decode("utf-8")
    db.commit()
    return {"status": "ok", "message": "密码修改成功"}
