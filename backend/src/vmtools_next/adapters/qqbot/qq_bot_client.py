"""QQ Bot HTTP API client — send group/private messages via QQ official API.

API docs: https://bot.qq.com/wiki/develop/api-v2/
"""
from __future__ import annotations

import asyncio
import json
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

    Also supports WebSocket event listening for @bot commands.
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
        self._ws_task: Optional[asyncio.Task] = None
        self._ws_running = False

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
        self._ws_running = False
        if self._ws_task:
            self._ws_task.cancel()
            try:
                await self._ws_task
            except asyncio.CancelledError:
                pass
            self._ws_task = None
        if self._client:
            await self._client.aclose()
            self._client = None

    # ── WebSocket Event Listener ────────────────────────────

    async def start_ws_listener(self) -> None:
        """Connect to QQ WSS gateway and listen for @bot commands."""
        self._ws_running = True
        self._ws_task = asyncio.create_task(self._ws_loop())

    async def _ws_loop(self) -> None:
        """WebSocket event loop — handle GROUP_AT_MESSAGE_CREATE."""
        import websockets
        while self._ws_running:
            try:
                await self._ensure_token()
                ws_url = await self._get_gateway_url()
                logger.info(f"QQ Bot WebSocket connecting: {ws_url[:60]}")
                async with websockets.connect(ws_url) as ws:
                    await self._ws_identify(ws)
                    await self._ws_listen(ws)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.warning(f"QQ Bot WebSocket error, reconnecting in 5s: {exc}")
                await asyncio.sleep(5)

    async def _get_gateway_url(self) -> str:
        resp = await self._client.get(
            "https://api.sgroup.qq.com/gateway/bot",
            headers=self._headers,
        )
        data = resp.json()
        if "url" not in data:
            raise RuntimeError(f"Gateway URL fetch failed: {data}")
        return data["url"]

    async def _ws_identify(self, ws) -> None:
        payload = {
            "op": 2,
            "d": {
                "token": f"QQBot {self._token}",
                "intents": 1 | (1 << 25),  # GUILDS + GROUP_AT_MESSAGE
                "shard": [0, 1],
                "properties": {"$os": "linux", "$browser": "vmtools", "$device": "server"},
            },
        }
        await ws.send(json.dumps(payload))

    async def _ws_listen(self, ws) -> None:
        heartbeat_task = None
        async for raw in ws:
            event = json.loads(raw)
            op = event.get("op")
            t = event.get("t")
            d = event.get("d", {})

            if op == 10:  # Hello
                interval = d["heartbeat_interval"]
                logger.info(f"QQ Bot WebSocket ready, heartbeat={interval}ms")
                heartbeat_task = asyncio.create_task(self._ws_heartbeat(ws, interval))

            if op == 11:  # Heartbeat ACK
                pass

            # Log all event types for debugging
            if t:
                logger.info(f"QQ Bot WS event: op={op} t={t}")

            if t == "READY":
                user = d.get("user", {})
                logger.info(f"QQ Bot WS ready: user={user.get('username')}")

            if t in ("GROUP_AT_MESSAGE_CREATE", "GROUP_MESSAGE_CREATE"):
                await self._handle_at_message(d)

        if heartbeat_task:
            heartbeat_task.cancel()

    async def _ws_heartbeat(self, ws, interval_ms: int) -> None:
        while self._ws_running:
            await asyncio.sleep(interval_ms / 1000)
            try:
                await ws.send(json.dumps({"op": 1, "d": {}}))
            except Exception:
                break

    async def _handle_at_message(self, d: dict) -> None:
        """Handle @bot commands or group messages containing /list."""
        content = (d.get("content", "") or "").strip()
        if "/list" not in content:
            return
        # Remove bot mention prefix (handles both <@!openid> and <@openid>)
        import re
        content = re.sub(r"<@!?\w+>", "", content).strip()
        group_id = d.get("group_id") or d.get("group_openid") or ""
        if not group_id:
            return

        logger.info(f"QQ Bot command: group={group_id} content={content}")

        if content == "/list":
            await self._cmd_list(group_id)

    async def _cmd_list(self, group_id: str) -> None:
        """Reply with current online player list from BlueMap."""
        try:
            from vmtools_next.main import get_bluemap_monitor
            monitor = get_bluemap_monitor()
            players: list[dict] = []
            if monitor:
                # Access the monitor's internal player state
                players = list(monitor._previous_players.values())
        except Exception:
            players = []

        if not players:
            await self.send_group_message(group_id, "📭 当前没有在线玩家")
            return

        # Group by world
        by_world: dict[str, list[str]] = {}
        labels = {"world": "主世界", "world_nether": "地狱", "world_the_end": "末地"}
        for p in players:
            w = p.get("world", "unknown")
            name = p.get("name", "?")
            by_world.setdefault(w, []).append(name)

        lines = [f"🌐 当前在线 {len(players)} 人："]
        for w, names in sorted(by_world.items()):
            label = labels.get(w, w)
            lines.append(f"\n【{label}】{len(names)}人")
            lines.append("  " + "、".join(names))

        msg = "\n".join(lines)
        # Truncate if too long (QQ limits at ~2000 chars)
        if len(msg) > 1800:
            msg = msg[:1800] + "\n...（列表过长已截断）"
        await self.send_group_message(group_id, msg)

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
        mention_openids: list[str] | None = None,
    ) -> dict:
        """Send a message to a QQ group.

        Args:
            group_openid: Group ID from QQ platform
            content: Message text
            msg_type: 0=text, 1=markdown
            markdown: Markdown object if msg_type=1
            mention_openids: If set, wraps message as markdown with <@!openid>
                to trigger QQ @mention notifications.
        """
        await self._ensure_token()
        async with self._rate_sem:
            if mention_openids:
                # QQ Bot API: msg_type=2 is markdown (NOT 1).
                # <@!openid> in markdown content triggers real @mention.
                # If bot lacks markdown capability, fall back to text.
                mentions = "".join(f"<@!{oid}>" for oid in mention_openids)
                md_content = f"{mentions} {content}"
                payload = {
                    "msg_type": 2,
                    "content": "",
                    "markdown": {"content": md_content},
                }
            else:
                payload = {
                    "msg_type": msg_type,
                    "content": content,
                }
                if markdown and msg_type == 2:
                    payload["markdown"] = markdown
                    payload["content"] = ""

            resp = await self._client.post(
                f"{self._base}/v2/groups/{group_openid}/messages",
                headers=self._headers,
                json=payload,
            )
            data = resp.json() if resp.text else {}
            if resp.status_code != 200:
                logger.warning(
                    "QQ send_group_message failed: HTTP %d body=%s payload=%s",
                    resp.status_code, resp.text[:300], payload,
                )
                # If markdown failed, retry as plain text
                if mention_openids and resp.status_code != 200:
                    mentions = "".join(f"<@!{oid}>" for oid in mention_openids)
                    text_payload = {
                        "msg_type": 0,
                        "content": f"{mentions} {content}",
                    }
                    resp2 = await self._client.post(
                        f"{self._base}/v2/groups/{group_openid}/messages",
                        headers=self._headers,
                        json=text_payload,
                    )
                    data = resp2.json() if resp2.text else {}
                    if resp2.status_code != 200:
                        logger.warning(
                            "QQ text fallback also failed: HTTP %d body=%s",
                            resp2.status_code, resp2.text[:300],
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

    async def list_group_members(self, group_openid: str) -> list[dict]:
        """Get all members of a group.

        Returns list of {member_openid, nickname, role, ...}
        """
        await self._ensure_token()
        resp = await self._client.get(
            f"{self._base}/v2/groups/{group_openid}/members",
            headers=self._headers,
        )
        data = resp.json() if resp.text else []
        return data if isinstance(data, list) else []
