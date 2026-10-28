"""子路径应用访问控制（供 nginx auth_request 调用）。

只做一件事：判断当前 JWT 对应的用户，是否有权进入指定子路径应用。

- site_admin：永远放行（保持既有行为）
- 白名单用户：仅对其被授权的应用放行

⚠️ 这些接口只返回 200/401/403，不返回任何用户数据，避免成为信息泄露面。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from vmtools_next.api.deps import get_optional_user
from vmtools_next.config import get_config
from vmtools_next.data.models.auth import UserModel
from vmtools_next.infra.logging import get_logger

logger = get_logger("api.access")

router = APIRouter(prefix="/api/access", tags=["access"])

_SITE_ADMIN = "site_admin"


def _require_site_admin_or_whitelist(
    user: UserModel | None,
    whitelist: list[str],
) -> None:
    """通过则静默返回；否则抛 401/403。"""
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="unauthorized")

    if getattr(user, "role", None) == _SITE_ADMIN:
        return

    gid = (getattr(user, "game_id", "") or "").strip()
    # ⚠️ 2026-10-19 审查修复（严重）：此处**必须**区分大小写精确比对。
    #   原实现用 `gid.lower() in {w.lower()}` 做不区分大小写匹配，但
    #   users.game_id 的 UNIQUE 索引（ix_users_game_id）在 SQLite 默认 BINARY
    #   collation 下是**区分大小写**的 —— 已实测 'happyzhou2991' 与
    #   'HAPPYZHOU2991' 可同时存在于 users 表。
    #   攻击路径：QQ 注册已开放 → 任何人注册 game_id='HAPPYZHOU2991'（role=user）
    #   → 走 magpie-check 时 lower() 命中白名单 → 直接进入 magpie 拿到全部
    #   供应商账号与网关密钥。属**白名单绕过 / 越权**。
    #   改为精确比对后，白名单语义与数据库唯一性语义一致。
    allowed = {w.strip() for w in whitelist if w and w.strip()}
    if gid in allowed:
        return

    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="forbidden")


@router.get("/magpie-check")
def magpie_check(
    user: UserModel | None = Depends(get_optional_user),
):
    """magpie 入口鉴权：site_admin 或 magpie 白名单用户。"""
    cfg = get_config()
    whitelist = list(getattr(cfg.access_control, "magpie_whitelist", []) or [])
    _require_site_admin_or_whitelist(user, whitelist)
    return {"ok": True}


@router.get("/dsh-check")
def dsh_check(
    user: UserModel | None = Depends(get_optional_user),
):
    """DSH 入口鉴权：**仅** site_admin（DSH 能执行任意命令，不给白名单开口子）。"""
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="unauthorized")
    if getattr(user, "role", None) != _SITE_ADMIN:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="forbidden")
    return {"ok": True}
