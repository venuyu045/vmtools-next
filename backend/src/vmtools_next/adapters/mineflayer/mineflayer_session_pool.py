"""Session pool for mineflayer bot WebSocket connections.

Manages MineflayerBridgeClient instances per bot, with health checks.
Unlike MccSessionPool, no event polling is needed — mineflayer pushes
events via WebSocket automatically.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

from .mineflayer_client import MineflayerBridgeClient

logger = logging.getLogger("vmtools.mineflayer_session_pool")


class MineflayerSessionPool:
    """Manages mineflayer bot WebSocket connections.

    One MineflayerBridgeClient per bot. Health checks via WS ping/pong
    (handled by the websockets library automatically).
    """

    def __init__(self, health_check_interval: float = 5.0):
        self._clients: dict[str, MineflayerBridgeClient] = {}
        self._health_check_interval = health_check_interval
        self._health_check_task: Optional[asyncio.Task] = None
        self._running = False

    @property
    def running(self) -> bool:
        return self._running

    def get_client(self, bot_id: str) -> Optional[MineflayerBridgeClient]:
        """Get the bridge client for a bot."""
        return self._clients.get(bot_id)

    def is_connected(self, bot_id: str) -> bool:
        client = self._clients.get(bot_id)
        return client is not None and client.is_connected

    def get_bot_status(self, bot_id: str) -> dict:
        """Return live connection status for a bot (aligned with MccSessionPool).

        mineflayer 没有 MCP HTTP 心跳，状态直接取自 WS 连接是否存活。
        """
        client = self._clients.get(bot_id)
        if client is not None and client.is_connected:
            return {
                "status": "online",
                "port": getattr(client, "port", None),
                "connected_at": getattr(client, "connected_at", None),
                "last_heartbeat": getattr(client, "last_heartbeat_at", None),
            }
        return {"status": "offline", "port": None}

    async def connect_bot(self, bot_id: str, host: str = "127.0.0.1",
                           port: int = 44444, auth_token: str | None = None) -> bool:
        """Connect to a mineflayer bot process.

        ``auth_token`` 仅为兼容 MCC 引擎的 connect 接口签名，mineflayer WS
        不校验 token，直接忽略。
        """
        # 如果已有连接，先断开
        existing = self._clients.get(bot_id)
        if existing:
            await existing.disconnect()

        client = MineflayerBridgeClient(host=host, port=port)
        # bot_ready 事件 → 确认登录 → instance.status = running（补充 stdout LOGIN_OK 通道）
        client.on_event(self._on_bot_event(bot_id))
        ok = await client.connect()
        if ok:
            self._clients[bot_id] = client
            logger.info("Bot %s connected at %s:%d", bot_id, host, port)
            # 同步 bot 状态到 DB + Socket.IO（前端 bot 卡片实时变绿）
            await self._sync_bot_status(bot_id, "online")
        else:
            logger.warning("Bot %s failed to connect at %s:%d", bot_id, host, port)
        return ok

    async def disconnect_bot(self, bot_id: str) -> None:
        """Disconnect a bot."""
        client = self._clients.pop(bot_id, None)
        if client:
            await client.disconnect()
            logger.info("Bot %s disconnected", bot_id)
            await self._sync_bot_status(bot_id, "offline")

    async def disconnect_all(self) -> None:
        """Disconnect all bots."""
        for bot_id in list(self._clients.keys()):
            await self.disconnect_bot(bot_id)

    async def start(self) -> None:
        """Start health check loop."""
        self._running = True
        self._health_check_task = asyncio.create_task(self._health_check_loop())
        logger.info("MineflayerSessionPool started (health check every %ss)",
                     self._health_check_interval)

    async def stop(self) -> None:
        """Stop health check loop and disconnect all bots."""
        self._running = False
        if self._health_check_task:
            self._health_check_task.cancel()
            try:
                await self._health_check_task
            except asyncio.CancelledError:
                pass
            self._health_check_task = None
        await self.disconnect_all()
        logger.info("MineflayerSessionPool stopped")

    async def _health_check_loop(self) -> None:
        """Periodic health check — WS library handles pings internally."""
        while self._running:
            try:
                await asyncio.sleep(self._health_check_interval)
                for bot_id, client in list(self._clients.items()):
                    if not client.is_connected:
                        logger.warning("Bot %s disconnected during health check", bot_id)
                        # 移除失效 client（监听循环已退出），由 MineflayerProcessManager
                        # 处理重启；同时同步状态
                        self._clients.pop(bot_id, None)
                        await self._sync_bot_status(bot_id, "offline")
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Health check error: %s", e)

    @staticmethod
    async def _sync_bot_status(bot_id: str, status: str) -> None:
        """Sync a bot's status to the mcc_bots row + broadcast Socket.IO event."""
        try:
            from vmtools_next.data.db import get_session_factory, sio
            from vmtools_next.data.models.logistics import MccBotModel
            Session = get_session_factory()
            db = Session()
            try:
                bot = db.query(MccBotModel).filter(
                    MccBotModel.bot_id == bot_id).first()
                if bot:
                    bot.status = status
                    db.commit()
            finally:
                db.close()
            await sio.emit("bot_status_update", {"bot_id": bot_id, "status": status})
        except Exception as e:
            logger.warning("Failed to sync bot status for %s: %s", bot_id, e)

    @staticmethod
    async def _persist_bot_state(bot_id: str, status: dict) -> None:
        """把 mineflayer status 推送（坐标/血量/饱食度）写入 DB 并广播 Socket.IO。

        与 MccSessionPool._persist_bot_state 对齐：状态页 bot_status_overview
        从 mcc_bots.current_location 读取坐标计算最近领地，MF 必须写库。
        """
        if not isinstance(status, dict) or not status.get("connected"):
            return
        import json as _json

        health: float | None = None
        food: int | None = None
        location: dict | None = None

        health_raw = status.get("health")
        if health_raw is not None:
            try:
                health = float(health_raw)
            except (TypeError, ValueError):
                health = None
        food_raw = status.get("food")
        if food_raw is not None:
            try:
                food = int(food_raw)
            except (TypeError, ValueError):
                food = None
        loc = status.get("position") or status.get("location") or status.get("pos")
        if isinstance(loc, dict):
            try:
                location = {
                    "x": round(float(loc.get("x", 0)), 1),
                    "y": round(float(loc.get("y", 0)), 1),
                    "z": round(float(loc.get("z", 0)), 1),
                }
            except (TypeError, ValueError):
                location = None

        from vmtools_next.data.db import get_session_factory, sio
        from vmtools_next.data.models.logistics import MccBotModel

        Session = get_session_factory()
        db = Session()
        try:
            bot = db.query(MccBotModel).filter(MccBotModel.bot_id == bot_id).first()
            if bot:
                bot.status = "online"
                if health is not None:
                    bot.current_health = health
                if food is not None:
                    bot.current_food = food
                if location is not None:
                    bot.current_location = _json.dumps(location, ensure_ascii=False)
                db.commit()
        except Exception as e:
            logger.warning("Persist MF bot state failed for %s: %s", bot_id, e)
        finally:
            db.close()

        payload: dict = {"bot_id": bot_id, "status": "online"}
        if health is not None:
            payload["current_health"] = health
        if food is not None:
            payload["current_food"] = food
        if location is not None:
            payload["current_location"] = location
        try:
            await sio.emit("bot_status_update", payload)
        except Exception as e:
            logger.warning("Emit bot_status_update failed for %s: %s", bot_id, e)

    def _on_bot_event(self, bot_id: str):
        """Return an event handler that syncs instance status on bot_ready/kicked/end."""
        from vmtools_next.data.models.mcc_remote import MccInstanceModel

        async def handler(event: str, data: dict) -> None:
            if event == "bot_ready":
                logger.info("Bot %s reported bot_ready (logged in)", bot_id)
                await self._sync_bot_status(bot_id, "online")
                # 同步关联 instance 状态
                try:
                    from vmtools_next.data.db import get_session_factory
                    Session = get_session_factory()
                    db = Session()
                    try:
                        inst = db.query(MccInstanceModel).filter(
                            MccInstanceModel.bot_id == bot_id,
                            MccInstanceModel.deleted_at.is_(None),
                        ).first()
                        if inst and inst.status != "running":
                            inst.status = "running"
                            db.commit()
                    finally:
                        db.close()
                except Exception as e:
                    logger.warning("Failed to sync instance status: %s", e)
            elif event == "status":
                # 定期状态推送（默认 5s，含 position/health/food）：
                # 同步坐标/血量/饱食度到 DB + Socket.IO，状态页据此显示坐标与最近领地
                await self._persist_bot_state(bot_id, data)
            elif event in ("bot_kicked", "bot_disconnected", "bot_error"):
                logger.info("Bot %s event %s: %s", bot_id, event, data)
                await self._sync_bot_status(bot_id, "error" if event == "bot_error" else "offline")

        return handler
