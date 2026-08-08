"""QQ 互联（connect.qq.com）OAuth2.0 认证服务。

实现「QQ 一键注册/登录」：
1. 生成授权跳转 URL（含 state 防 CSRF）
2. 回调换取 access_token + openid（QQ 号不公开，openid 对应用唯一 → 一 QQ 一账号）
3. 拉取用户昵称/头像
4. 短期 ticket 机制：callback 返回 /register?qq_ticket=xxx，前端凭 ticket 完成注册/登录

申请地址：https://connect.qq.com → 创建「网站应用」，配置回调域名为本站域名。
"""
from __future__ import annotations

import secrets
import time
import urllib.parse
from typing import Optional

import httpx

from vmtools_next.config import get_config
from vmtools_next.infra.logging import get_logger

logger = get_logger("qq_connect")

AUTHORIZE_URL = "https://graph.qq.com/oauth2.0/authorize"
TOKEN_URL = "https://graph.qq.com/oauth2.0/token"
ME_URL = "https://graph.qq.com/oauth2.0/me"
USER_INFO_URL = "https://graph.qq.com/user/get_user_info"

# state / ticket 内存存储（单 worker 足够；重启后失效→用户重新授权即可）
_STATES: dict[str, float] = {}       # state -> expires_at
_TICKETS: dict[str, dict] = {}       # ticket -> {openid, nickname, avatar, expires_at}


class QqOAuthError(Exception):
    """QQ 互联 OAuth 流程错误。"""


def is_configured() -> bool:
    cfg = get_config().qq_connect
    return bool(cfg.enabled and cfg.app_id and cfg.app_key and cfg.redirect_uri)


def get_authorize_url() -> str:
    """生成 QQ 授权跳转 URL（用户点击后跳转 QQ 登录页）。"""
    if not is_configured():
        raise QqOAuthError("QQ 互联未配置（qq_connect.app_id/app_key/redirect_uri）")
    cfg = get_config().qq_connect
    state = secrets.token_urlsafe(16)
    _STATES[state] = time.time() + cfg.state_ttl_seconds
    params = {
        "response_type": "code",
        "client_id": cfg.app_id,
        "redirect_uri": cfg.redirect_uri,
        "state": state,
        "scope": "get_user_info",
    }
    return f"{AUTHORIZE_URL}?{urllib.parse.urlencode(params)}"


def _validate_state(state: str) -> None:
    exp = _STATES.pop(state, None)
    if exp is None or time.time() > exp:
        raise QqOAuthError("state 无效或已过期，请重新发起 QQ 登录")


def _parse_query_response(text: str) -> dict:
    """QQ token/me 接口返回 query-string 格式，统一解析为 dict。"""
    result = {}
    for part in text.split("&"):
        if "=" in part:
            k, v = part.split("=", 1)
            result[urllib.parse.unquote_plus(k)] = urllib.parse.unquote_plus(v)
    return result


async def exchange_code(code: str, state: str) -> tuple[str, str]:
    """用授权 code 换取 (access_token, openid)。

    openid 对同一 QQ 互联应用全局唯一——是「一个 QQ 只能注册一个账号」的依据。
    """
    _validate_state(state)
    cfg = get_config().qq_connect
    params = {
        "grant_type": "authorization_code",
        "client_id": cfg.app_id,
        "client_secret": cfg.app_key,
        "code": code,
        "redirect_uri": cfg.redirect_uri,
    }
    async with httpx.AsyncClient(timeout=httpx.Timeout(10.0)) as client:
        resp = await client.get(TOKEN_URL, params=params)
        data = _parse_query_response(resp.text)
        access_token = data.get("access_token")
        if not access_token:
            raise QqOAuthError(f"QQ token 获取失败: {resp.text[:300]}")

        me = await client.get(ME_URL, params={"access_token": access_token})
        me_text = me.text
        # 形如 callback( {"client_id":"...","openid":"..."} ); 提取 JSON
        if "callback(" in me_text:
            me_text = me_text[me_text.index("(") + 1: me_text.rindex(")")]
        me_data = _parse_query_response(me_text.replace(" ", ""))
        openid = me_data.get("openid") or me_data.get('"openid"')
        if not openid:
            raise QqOAuthError(f"QQ openid 获取失败: {me.text[:300]}")
        return access_token, openid


async def get_user_info(access_token: str, openid: str) -> dict:
    """拉取 QQ 用户昵称/头像。失败时返回空 dict（不影响注册）。"""
    cfg = get_config().qq_connect
    params = {
        "access_token": access_token,
        "oauth_consumer_key": cfg.app_id,
        "openid": openid,
    }
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(10.0)) as client:
            resp = await client.get(USER_INFO_URL, params=params)
            data = resp.json()
            if data.get("ret") == 0:
                return {
                    "nickname": data.get("nickname", ""),
                    "avatar": data.get("figureurl_qq_2") or data.get("figureurl_qq_1") or "",
                }
            logger.warning("QQ get_user_info failed: {}", data.get("msg"))
    except Exception as exc:
        logger.warning("QQ get_user_info error: {}", exc)
    return {}


def create_ticket(openid: str, nickname: str = "", avatar: str = "") -> str:
    """创建一次性短期 ticket（前端注册/登录时凭此换取 openid）。"""
    cfg = get_config().qq_connect
    ticket = secrets.token_urlsafe(24)
    _TICKETS[ticket] = {
        "openid": openid,
        "nickname": nickname,
        "avatar": avatar,
        "expires_at": time.time() + cfg.ticket_ttl_seconds,
    }
    return ticket


def consume_ticket(ticket: str) -> Optional[dict]:
    """消费 ticket 并返回 {openid, nickname, avatar}；无效/过期返回 None。"""
    data = _TICKETS.pop(ticket, None)
    if not data:
        return None
    if time.time() > data["expires_at"]:
        return None
    return {
        "openid": data["openid"],
        "nickname": data.get("nickname", ""),
        "avatar": data.get("avatar", ""),
    }
