"""QQ Bot HTTP API client — send group/private messages via QQ official API.

API docs: https://bot.qq.com/wiki/develop/api-v2/
"""
from __future__ import annotations

import asyncio
import time
from typing import Optional

import httpx

from vmtools_next.infra.logging import get_logger

logger = get_logger("qqbot")

# QQ Bot API base URLs
BASE_URL = "https://api.sgroup.qq.com"
SANDBOX_URL = "https://sandbox.api.sgroup.qq.com"


class QqBotClient:
    """Async client for QQ official bot HTTP API.

    Manages access token lifecycle and provides high-level send_message helpers.
    Rate-limited: 60 QPM global, 20 QPM per group (verified bot).
    """

    def __init__(
        self,
        app_id: str,
        app_secret: str,
        sandbox: bool = False,
    ):
        self._app_id = app_id
        self._app_secret = app_secret
        self._sandbox = sandbox
        self._base = SANDBOX_URL if sandbox else BASE_URL
        self._token: Optional[str] = None
        self._token_expires_at: float = 0
        self._client: Optional[httpx.AsyncClient] = None
        self._rate_sem = asyncio.Semaphore(50)  # safe margin under 60 QPM

    async def __aenter__(self):
        await self.start()
        return self

    async def __aexit__(self, *args):
        await self.stop()

    async def start(self) -> bool:
        """Obtain access token, returns True on success."""
        self._client = httpx.AsyncClient(timeout=httpx.Timeout(10.0))
        try:
            await self._ensure_token()
            logger.info("QQ Bot connected: app_id=%s", self._app_id)
            return True
        except Exception as e:
            logger.warning("QQ Bot token fetch failed: %s", e)
            return False

    async def stop(self):
        if self._client:
            await self._client.aclose()
            self._client = None

    # ── Token ────────────────────────────────────────────────

    async def _ensure_token(self):
        """Refresh access token if expired or not set."""
        if self._token and time.time() < self._token_expires_at - 60:
            return
        resp = await self._client.post(
            "https://bots.qq.com/app/getAppAccessToken",
            json={"appId": self._app_id, "clientSecret": self._app_secret},
        )
        data = resp.json()
        if resp.status_code != 200 or "access_token" not in data:
            raise RuntimeError(f"Token fetch failed: HTTP {resp.status_code} {resp.text[:300]}")
        self._token = data["access_token"]
        expires_in = data.get("expires_in", 7200)
        self._token_expires_at = time.time() + int(expires_in)

    @property
    def _headers(self) -> dict:
        return {
            "Authorization": f"QQBot {self._token}",
            "Content-Type": "application/json",
        }

    # ── Send Messages ────────────────────────────────────────

    async def send_group_message(
        self,
        group_openid: str,
        content: str,
        msg_type: int = 0,
        markdown: Optional[dict] = None,
    ) -> dict:
        """Send a message to a QQ group.

        Args:
            group_openid: Group ID from QQ platform
            content: Plain text message
            msg_type: 0=text, 1=markdown, 2=ark, 3=embed, 4=media
            markdown: Markdown message object if msg_type=1
        """
        await self._ensure_token()
        async with self._rate_sem:
            payload: dict = {
                "msg_type": msg_type,
                "content": content,
            }
            if markdown and msg_type == 1:
                payload["markdown"] = markdown

            resp = await self._client.post(
                f"{self._base}/v2/groups/{group_openid}/messages",
                headers=self._headers,
                json=payload,
            )
            data = resp.json() if resp.text else {}
            if resp.status_code != 200:
                logger.warning(
                    "QQ send_group_message failed: HTTP %d body=%s",
                    resp.status_code, resp.text[:300],
                )
            return data

    async def send_private_message(
        self,
        openid: str,
        content: str,
        msg_type: int = 0,
    ) -> dict:
        """Send a private message to a QQ user."""
        await self._ensure_token()
        async with self._rate_sem:
            resp = await self._client.post(
                f"{self._base}/v2/users/{openid}/messages",
                headers=self._headers,
                json={"msg_type": msg_type, "content": content},
            )
            data = resp.json() if resp.text else {}
            if resp.status_code != 200:
                logger.warning(
                    "QQ send_private_message failed: HTTP %d body=%s",
                    resp.status_code, resp.text[:300],
                )
            return data

    async def list_groups(self) -> list[dict]:
        """Get all groups the bot has joined.

        Returns list of {group_openid, group_name, member_count, ...}
        """
        await self._ensure_token()
        resp = await self._client.get(
            f"{self._base}/users/@me/groups",
            headers=self._headers,
        )
        data = resp.json() if resp.text else []
        return data if isinstance(data, list) else []
