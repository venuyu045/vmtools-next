"""子路径应用访问控制（供 nginx auth_request 调用）。

只做一件事：判断当前 JWT 对应的用户，是否有权进入指定子路径应用。

- site_admin：永远放行（保持既有行为）
- 白名单用户：仅对其被授权的应用放行

⚠️ 这些接口只返回 200/401/403，不返回任何用户数据，避免成为信息泄露面。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from vmtools_next.api.deps import get_db, get_optional_user
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
    # 大小写不敏感比对，避免玩家改名/大小写差异导致误拒
    allowed = {w.strip().lower() for w in whitelist if w and w.strip()}
    if gid.lower() in allowed:
        return

    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="forbidden")


@router.get("/magpie-check")
def magpie_check(
    user: UserModel | None = Depends(get_optional_user),
    db: Session = Depends(get_db),
):
    """magpie 入口鉴权：site_admin 或 magpie 白名单用户。"""
    cfg = get_config()
    whitelist = list(getattr(cfg.access_control, "magpie_whitelist", []) or [])
    _require_site_admin_or_whitelist(user, whitelist)
    return {"ok": True}


@router.get("/dsh-check")
def dsh_check(
    user: UserModel | None = Depends(get_optional_user),
    db: Session = Depends(get_db),
):
    """DSH 入口鉴权：**仅** site_admin（DSH 能执行任意命令，不给白名单开口子）。"""
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="unauthorized")
    if getattr(user, "role", None) != _SITE_ADMIN:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="forbidden")
    return {"ok": True}
