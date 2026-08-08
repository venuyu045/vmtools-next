"""Authentication API routes."""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from vmtools_next.api.deps import get_db, get_current_user
from vmtools_next.config import get_config
from vmtools_next.data.models.auth import UserModel
from vmtools_next.infra.logging import get_logger

logger = get_logger("auth")

# ── 登录限流（防暴力破解，M1） ──
_LOGIN_ATTEMPTS: dict[str, tuple[float, int]] = {}
_LOGIN_LIMIT = 5          # 窗口内最大失败尝试次数
_LOGIN_WINDOW = 60.0      # 窗口秒数


def _check_login_rate_limit(key: str) -> None:
    import time as _time
    now = _time.monotonic()
    ts, cnt = _LOGIN_ATTEMPTS.get(key, (0.0, 0))
    if now - ts > _LOGIN_WINDOW:
        ts, cnt = now, 0
    if cnt >= _LOGIN_LIMIT:
        raise HTTPException(429, "尝试过于频繁，请稍后再试")
    _LOGIN_ATTEMPTS[key] = (ts, cnt + 1)


def _reset_login_rate_limit(key: str) -> None:
    _LOGIN_ATTEMPTS.pop(key, None)

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
    qq_ticket: str = ""  # QQ 互联认证后签发的一次性 ticket（注册必须携带）


class ChangePasswordRequest(BaseModel):
    old_password: str
    new_password: str


class QqTicketLoginRequest(BaseModel):
    qq_ticket: str


def _make_token(user: UserModel) -> str:
    config = get_config()
    return jwt.encode(
        {"sub": user.id, "exp": datetime.now(timezone.utc) + timedelta(hours=24)},
        config.server.secret_key,
        algorithm=config.server.jwt_algorithm,
    )


@router.post("/login", response_model=LoginResponse)
def login(data: LoginRequest, request: Request, db: Session = Depends(get_db)):
    """Login with game_id and password."""
    client_ip = request.client.host if request.client else "unknown"
    rate_key = f"{data.game_id.lower()}|{client_ip}"
    _check_login_rate_limit(rate_key)

    user = db.query(UserModel).filter(UserModel.game_id == data.game_id).first()
    if not user:
        raise HTTPException(401, "Invalid credentials")

    if not bcrypt.checkpw(data.password.encode("utf-8"), user.password_hash.encode("utf-8")):
        raise HTTPException(401, "Invalid credentials")

    if user.status != "approved":
        raise HTTPException(403, "User not approved")

    _reset_login_rate_limit(rate_key)
    # 记录上次上线时间（成员管理「上次上线」列）
    user.last_seen_at = datetime.now(timezone.utc)
    db.commit()
    return LoginResponse(token=_make_token(user), user_id=user.id, game_id=user.game_id, role=user.role)


@router.post("/register")
def register(data: RegisterRequest, db: Session = Depends(get_db)):
    """注册新账号——必须经过 QQ 互联认证（qq_ticket）。

    认证通过后直接创建账号：status=approved（无需管理员审核）、role=user（用户权限组）。
    一个 QQ（openid）只能注册一个账号；Game ID 也全局唯一。
    """
    # 1) QQ 认证校验
    from vmtools_next.core.qq_oauth import consume_ticket, is_configured
    if not is_configured():
        raise HTTPException(503, "QQ 互联未配置，暂不支持注册")
    if not data.qq_ticket:
        raise HTTPException(400, "请先使用 QQ 认证")
    qq_info = consume_ticket(data.qq_ticket)
    if not qq_info:
        raise HTTPException(400, "QQ 认证已过期，请重新发起 QQ 登录")

    openid = qq_info["openid"]
    # 1.5) 入参校验（与 change-password 口径一致，M8）
    if len(data.password) < 6:
        raise HTTPException(400, "密码长度不能少于 6 位")
    gid = (data.game_id or "").strip()
    if not gid or len(gid) > 32 or any(c in gid for c in " \t\r\n"):
        raise HTTPException(400, "Game ID 格式不合法")
    # 2) 唯一性校验
    if db.query(UserModel).filter(UserModel.game_id == data.game_id).first():
        raise HTTPException(400, "Game ID already registered")
    if db.query(UserModel).filter(UserModel.qq_openid == openid).first():
        raise HTTPException(400, "该 QQ 已注册过账号（一个 QQ 只能注册一个账号）")

    # 3) 创建账号：approved + user
    password_hash = bcrypt.hashpw(data.password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
    user = UserModel(
        id=str(uuid.uuid4()),
        game_id=data.game_id,
        password_hash=password_hash,
        display_name=data.display_name or qq_info.get("nickname") or data.game_id,
        role="user",
        status="approved",
        approved_at=datetime.now(timezone.utc),
        qq_openid=openid,
        qq_nickname=qq_info.get("nickname") or "",
    )
    db.add(user)
    db.commit()

    return {"status": "approved", "message": "注册成功", "token": _make_token(user)}


@router.get("/qq/login")
def qq_login():
    """返回 QQ 互联授权跳转 URL（前端整页跳转）。"""
    from vmtools_next.core.qq_oauth import get_authorize_url, is_configured
    if not is_configured():
        raise HTTPException(503, "QQ 互联未配置，暂不支持 QQ 登录")
    return {"auth_url": get_authorize_url()}


@router.get("/qq/callback")
async def qq_callback(code: str = "", state: str = ""):
    """QQ 授权回调：换 openid → 签发一次性 ticket → 302 到前端。

    - 已注册用户：前端凭 ticket 调 /api/auth/qq/ticket-login 直接登录
    - 未注册用户：前端跳注册页预填 QQ 信息并完成注册
    """
    from vmtools_next.core.qq_oauth import (
        QqOAuthError, create_ticket, exchange_code, get_user_info, is_configured,
    )
    if not is_configured():
        raise HTTPException(503, "QQ 互联未配置")
    if not code or not state:
        raise HTTPException(400, "QQ 回调参数缺失")

    try:
        access_token, openid = await exchange_code(code, state)
        info = await get_user_info(access_token, openid)
        ticket = create_ticket(openid, info.get("nickname", ""), info.get("avatar", ""))
        return RedirectResponse(url=f"/login?qq_ticket={ticket}", status_code=302)
    except QqOAuthError as exc:
        raise HTTPException(400, str(exc))
    except Exception:
        logger.exception("QQ 认证回调失败")
        raise HTTPException(500, "QQ 认证失败，请稍后再试")


@router.post("/qq/ticket-login")
def qq_ticket_login(data: QqTicketLoginRequest, db: Session = Depends(get_db)):
    """凭 QQ ticket 登录：已注册 → 返回 token；未注册 → need_register=true。"""
    from vmtools_next.core.qq_oauth import consume_ticket
    qq_info = consume_ticket(data.qq_ticket)
    if not qq_info:
        raise HTTPException(400, "QQ 认证已过期，请重新发起 QQ 登录")

    user = db.query(UserModel).filter(UserModel.qq_openid == qq_info["openid"]).first()
    if user:
        if user.status != "approved":
            raise HTTPException(403, "User not approved")
        user.last_seen_at = datetime.now(timezone.utc)
        db.commit()
        return {
            "need_register": False,
            "token": _make_token(user),
            "user_id": user.id,
            "game_id": user.game_id,
            "role": user.role,
            "nickname": qq_info.get("nickname", ""),
        }
    return {
        "need_register": True,
        "nickname": qq_info.get("nickname", ""),
        "avatar": qq_info.get("avatar", ""),
    }


@router.get("/me")
def get_me(user=Depends(get_current_user), db: Session = Depends(get_db)):
    """Get current user info；同时记录本次访问（上次上线时间 = 最近一次访问网页时间）。"""
    user.last_seen_at = datetime.now(timezone.utc)
    db.commit()
    return {
        "id": user.id,
        "game_id": user.game_id,
        "display_name": user.display_name,
        "role": user.role,
        "status": user.status,
        "organization_id": user.organization_id,
        "last_seen_at": user.last_seen_at,
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
