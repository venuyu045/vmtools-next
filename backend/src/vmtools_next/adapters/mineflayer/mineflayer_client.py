"""WebSocket client for communication with a mineflayer bot process.

MineflayerBridgeClient connects to a Node.js mineflayer process via WebSocket
and provides high-level methods that mirror MccMcpClient's API surface.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from typing import Any, Optional

import websockets

from vmtools_next.adapters.abstract.bot_agent import AbstractBotAgent

from .protocol import (
    METHOD_MOVE_TO,
    METHOD_LOOK_AT,
    METHOD_GET_PLAYER_STATE,
    METHOD_CANCEL_PATHING,
    METHOD_IS_PLAYER_NEARBY,
    METHOD_PLACE_BLOCK,
    METHOD_DIG_BLOCK,
    METHOD_GET_WORLD_BLOCK_AT,
    METHOD_SCAN_NEARBY_BLOCKS,
    METHOD_SELECT_HOTBAR_ITEM,
    METHOD_SET_QUICK_BAR_SLOT,
    METHOD_GET_INVENTORY_SNAPSHOT,
    METHOD_OPEN_CONTAINER_AT,
    METHOD_CLOSE_CONTAINER,
    METHOD_GET_CONTAINER_SNAPSHOT,
    METHOD_WITHDRAW_CONTAINER_ITEM,
    METHOD_DEPOSIT_CONTAINER_ITEM,
    METHOD_SERVUX_HANDSHAKE,
    METHOD_PREVIEW_CONTAINER_AT,
    METHOD_SEND_CHAT,
    METHOD_RUN_COMMAND,
    METHOD_GET_SERVER_INFO,
    METHOD_FIND_BLOCKS,
    DEFAULT_CMD_TIMEOUT,
    MOVE_TIMEOUT,
    CONTAINER_TIMEOUT,
)

logger = logging.getLogger("vmtools.mineflayer_client")

# ── MCP 兼容错误 ──

class MineflayerError(Exception):
    """Base error for mineflayer bridge operations."""
    def __init__(self, message: str, code: int = -1, data: Any = None):
        super().__init__(message)
        self.code = code
        self.data = data


class MineflayerTimeout(MineflayerError):
    def __init__(self, message: str = "Operation timed out"):
        super().__init__(message, code=-2)


class MineflayerConnectionError(MineflayerError):
    def __init__(self, message: str = "Not connected"):
        super().__init__(message, code=-3)


class MineflayerBridgeClient(AbstractBotAgent):
    """WebSocket client for one mineflayer bot process.

    Usage:
        client = MineflayerBridgeClient(host="127.0.0.1", port=44444)
        await client.connect()
        result = await client.place_block(x=100, y=64, z=200, face="UP")
        await client.disconnect()
    """

    def __init__(self, host: str = "127.0.0.1", port: int = 44444):
        self._ws_url = f"ws://{host}:{port}"
        self._ws: Optional[websockets.WebSocketClientProtocol] = None
        self._pending: dict[str, asyncio.Future] = {}
        self._connected = False
        self._listen_task: Optional[asyncio.Task] = None
        self._last_status: dict = {}
        self._event_handlers: list = []
        self._bot_ready = False
        self._username: str | None = None

    # ── 状态与事件 ──

    @property
    def bot_ready(self) -> bool:
        """True once the bot process reports a successful mineflayer login."""
        return self._bot_ready

    @property
    def username(self) -> str | None:
        return self._username

    @property
    def last_status(self) -> dict:
        return self._last_status

    def on_event(self, handler) -> None:
        """Register an event handler (async or sync) receiving (event, data)."""
        self._event_handlers.append(handler)

    # ── 连接管理 ──

    @property
    def is_connected(self) -> bool:
        return self._connected and self._ws is not None

    async def connect(self, timeout: float = 10.0) -> bool:
        """Connect to the mineflayer bot's WebSocket server."""
        try:
            self._ws = await asyncio.wait_for(
                websockets.connect(self._ws_url, ping_interval=10, ping_timeout=5),
                timeout=timeout,
            )
            self._connected = True
            self._listen_task = asyncio.create_task(self._listen_loop())
            logger.info("Connected to mineflayer bot at %s", self._ws_url)
            return True
        except asyncio.TimeoutError:
            logger.warning("Connection to %s timed out", self._ws_url)
            return False
        except Exception as e:
            logger.warning("Failed to connect to %s: %s", self._ws_url, e)
            return False

    async def disconnect(self) -> None:
        """Disconnect from the mineflayer bot."""
        if self._listen_task:
            self._listen_task.cancel()
            try:
                await self._listen_task
            except asyncio.CancelledError:
                pass
            self._listen_task = None

        if self._ws:
            try:
                await self._ws.close()
            except Exception:
                pass
            self._ws = None

        self._connected = False

        # 清理挂起的请求
        for fut in self._pending.values():
            if not fut.done():
                fut.cancel()
        self._pending.clear()

    # ── 消息监听 ──

    async def _listen_loop(self) -> None:
        """Receive messages from WebSocket and dispatch to pending futures or events."""
        try:
            while self._ws is not None:
                try:
                    raw = await asyncio.wait_for(self._ws.recv(), timeout=30.0)
                except asyncio.TimeoutError:
                    continue  # recv timeout, just loop to check if still connected
                except (websockets.ConnectionClosed, ConnectionError, OSError) as recv_err:
                    # 连接已关闭：终止循环，由外层 finally 清理。
                    # 不能 continue —— 否则 recv 会反复抛错、每圈打 warning 日志，
                    # 导致日志刷屏（413万行）拖垮服务（历史事故：服务反复卡死）。
                    logger.info("Listen loop connection closed: %s", recv_err)
                    break
                except Exception as recv_err:
                    # 其它异常：限频（0.5s 退避）后继续，避免日志爆炸
                    logger.warning("Listen loop recv error: %s", recv_err)
                    await asyncio.sleep(0.5)
                    continue

                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    continue

                msg_type = msg.get("type")

                if msg_type == "response":
                    await self._handle_response(msg)
                elif msg_type == "event":
                    self._handle_event(msg)
                elif msg_type == "status":
                    self._handle_status(msg)
        except websockets.ConnectionClosed:
            logger.info("WebSocket connection closed")
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error("Listen loop error: %s", e, exc_info=True)
        finally:
            self._connected = False
            # 终结所有挂起的请求
            for fut in self._pending.values():
                if not fut.done():
                    fut.set_exception(MineflayerConnectionError("Connection lost"))
            self._pending.clear()

    async def _handle_response(self, msg: dict) -> None:
        request_id = msg.get("request_id")
        fut = self._pending.pop(request_id, None)
        if fut and not fut.done():
            if msg.get("success"):
                fut.set_result(msg.get("result", {}))
            else:
                fut.set_exception(MineflayerError(
                    msg.get("error", "Unknown error"), code=-1
                ))

    def _handle_event(self, msg: dict) -> None:
        event_name = msg.get("event")
        data = msg.get("data", {})
        logger.debug("Event: %s %s", event_name, data)
        if event_name == "bot_ready":
            self._bot_ready = True
            self._username = data.get("username") or self._username
        # 分发到事件处理器（含 bot_ready / bot_disconnected / bot_kicked 等）
        for handler in list(self._event_handlers):
            try:
                result = handler(event_name, data)
                if asyncio.iscoroutine(result):
                    asyncio.create_task(result)
            except Exception as e:
                logger.warning("Event handler error for %s: %s", event_name, e)

    def _handle_status(self, msg: dict) -> None:
        status = msg.get("bot_status", {})
        self._last_status = status
        logger.debug("Status update: connected=%s", status.get("connected"))

    # ── 请求-响应核心 ──

    async def _send_request(self, method: str, params: dict = None,
                            timeout: float = DEFAULT_CMD_TIMEOUT) -> dict:
        """Send a request and wait for the response."""
        if not self.is_connected:
            raise MineflayerConnectionError("Not connected to bot")

        request_id = str(uuid.uuid4())
        payload = {
            "type": "request",
            "request_id": request_id,
            "method": method,
            "params": params or {},
        }

        fut = asyncio.get_event_loop().create_future()
        self._pending[request_id] = fut

        try:
            await self._ws.send(json.dumps(payload))
            result = await asyncio.wait_for(fut, timeout=timeout)
            return result
        except asyncio.TimeoutError:
            self._pending.pop(request_id, None)
            raise MineflayerTimeout(f"{method} timed out after {timeout}s")
        except Exception as e:
            self._pending.pop(request_id, None)
            if isinstance(e, MineflayerError):
                raise
            raise MineflayerError(str(e))

    # ── 方块操作 ──

    async def place_block(self, x: int, y: int, z: int, face: str = "UP",
                          hand: str = "MAIN_HAND", look_at_block: bool = True) -> dict:
        return await self._send_request(METHOD_PLACE_BLOCK, {
            "x": x, "y": y, "z": z, "face": face,
        }, timeout=DEFAULT_CMD_TIMEOUT)

    async def dig_block(self, x: int, y: int, z: int) -> dict:
        return await self._send_request(METHOD_DIG_BLOCK, {
            "x": x, "y": y, "z": z,
        }, timeout=DEFAULT_CMD_TIMEOUT)

    async def get_world_block_at(self, x: int, y: int, z: int) -> dict:
        return await self._send_request(METHOD_GET_WORLD_BLOCK_AT, {
            "x": x, "y": y, "z": z,
        }, timeout=DEFAULT_CMD_TIMEOUT)

    async def scan_nearby_blocks(self, radius: int = 16, max_count: int = 100,
                                  matching: str = None) -> dict:
        params = {"radius": radius, "max_count": max_count}
        if matching:
            params["matching"] = matching
        return await self._send_request(METHOD_SCAN_NEARBY_BLOCKS, params,
                                        timeout=DEFAULT_CMD_TIMEOUT)

    # ── 移动 ──

    async def move_to(self, x: int, y: int, z: int,
                       max_offset: int = 3, timeout_ms: int = 15000) -> dict:
        return await self._send_request(METHOD_MOVE_TO, {
            "x": x, "y": y, "z": z,
            "max_offset": max_offset,
            "timeout_ms": timeout_ms,
        }, timeout=timeout_ms / 1000 + 5.0)

    async def look_at(self, x: int, y: int, z: int) -> dict:
        return await self._send_request(METHOD_LOOK_AT, {
            "x": x, "y": y, "z": z,
        }, timeout=DEFAULT_CMD_TIMEOUT)

    async def get_player_state(self) -> dict:
        return await self._send_request(METHOD_GET_PLAYER_STATE, {},
                                        timeout=DEFAULT_CMD_TIMEOUT)

    async def cancel_pathing(self) -> dict:
        return await self._send_request(METHOD_CANCEL_PATHING, {},
                                        timeout=5.0)

    async def is_player_nearby(self, radius: int = 10) -> dict:
        return await self._send_request(METHOD_IS_PLAYER_NEARBY, {
            "radius": radius,
        }, timeout=DEFAULT_CMD_TIMEOUT)

    # ── 物品栏 ──

    async def select_hotbar_item(self, item_type: str,
                                  prefer_lowest_slot: bool = True) -> dict:
        return await self._send_request(METHOD_SELECT_HOTBAR_ITEM, {
            "item_type": item_type,
            "prefer_lowest_slot": prefer_lowest_slot,
        }, timeout=DEFAULT_CMD_TIMEOUT)

    async def set_quick_bar_slot(self, slot_index: int) -> dict:
        return await self._send_request(METHOD_SET_QUICK_BAR_SLOT, {
            "slot_index": slot_index,
        }, timeout=DEFAULT_CMD_TIMEOUT)

    async def get_inventory_snapshot(self, inventory_id: int = 0) -> dict:
        """Get inventory snapshot, normalized to MCC's snapshot schema.

        Consumers (InventoryScanner, LogisticsRunner, BuildStateMachine,
        /mcc-bots/{id}/inventory) read ``{"items": [{type, displayName, count, slot}]}``
        — mineflayer returns ``{name, type, display_name, ...}`` per item, so map it.
        """
        result = await self._send_request(METHOD_GET_INVENTORY_SNAPSHOT, {},
                                          timeout=DEFAULT_CMD_TIMEOUT)
        if isinstance(result, dict) and isinstance(result.get("items"), list):
            items = []
            for s in result["items"]:
                if not isinstance(s, dict):
                    continue
                item_id = (s.get("type") or s.get("name") or s.get("itemId") or "").strip()
                if not item_id:
                    continue
                items.append({
                    "slot": s.get("slot", -1),
                    "type": item_id,
                    "displayName": s.get("displayName") or s.get("display_name") or item_id,
                    "count": s.get("count", s.get("amount", 0)) or 0,
                    "maxStackSize": s.get("max_stack_size", s.get("maxStackSize", 64)),
                })
            result["items"] = items
        return result

    # ── 容器 ──

    async def open_container_at(self, x: int, y: int, z: int,
                                 timeout_ms: int = 5000) -> dict:
        return await self._send_request(METHOD_OPEN_CONTAINER_AT, {
            "x": x, "y": y, "z": z,
        }, timeout=timeout_ms / 1000 + 5.0)

    async def close_container(self, container_id: str,
                               timeout_ms: int = 5000) -> dict:
        return await self._send_request(METHOD_CLOSE_CONTAINER, {
            "container_id": container_id,
        }, timeout=timeout_ms / 1000 + 2.0)

    async def get_container_snapshot(self, container_id: str) -> dict:
        return await self._send_request(METHOD_GET_CONTAINER_SNAPSHOT, {
            "container_id": container_id,
        }, timeout=DEFAULT_CMD_TIMEOUT)

    async def withdraw_container_item(self, item_type: str, count: int = 64,
                                       container_id: str = None) -> dict:
        return await self._send_request(METHOD_WITHDRAW_CONTAINER_ITEM, {
            "item_type": item_type,
            "count": count,
            "container_id": container_id,
        }, timeout=DEFAULT_CMD_TIMEOUT)

    async def deposit_container_item(self, item_type: str, count: int = 64,
                                      container_id: str = None) -> dict:
        return await self._send_request(METHOD_DEPOSIT_CONTAINER_ITEM, {
            "item_type": item_type,
            "count": count,
            "container_id": container_id,
        }, timeout=DEFAULT_CMD_TIMEOUT)

    # ── Servux 容器预览（不打开容器） ──

    async def servux_handshake(self, timeout_ms: int = 4000) -> dict:
        """与服务器 Servux 插件握手，返回 {success, version?, error?}."""
        return await self._send_request(METHOD_SERVUX_HANDSHAKE, {
            "timeout_ms": timeout_ms,
        }, timeout=max(3.0, timeout_ms / 1000 + 2.0))

    async def preview_container_at(self, x: int, y: int, z: int,
                                    timeout_ms: int = 5000) -> dict:
        """通过 Servux 协议预览容器内容（不打开容器）。

        Returns:
            {"success": True, "items": [{item_id, display_name, count, slot}], "source": "servux"}
            或 {"success": False, "error": "..."}
        """
        return await self._send_request(METHOD_PREVIEW_CONTAINER_AT, {
            "x": x, "y": y, "z": z, "timeout_ms": timeout_ms,
        }, timeout=timeout_ms / 1000 + 5.0)

    # ── 聊天 ──

    async def send_chat(self, message: str) -> dict:
        return await self._send_request(METHOD_SEND_CHAT, {
            "message": message,
        }, timeout=DEFAULT_CMD_TIMEOUT)

    async def run_command(self, command: str) -> dict:
        return await self._send_request(METHOD_RUN_COMMAND, {
            "command": command,
        }, timeout=DEFAULT_CMD_TIMEOUT)

    # ── 世界查询 ──

    async def get_server_info(self) -> dict:
        return await self._send_request(METHOD_GET_SERVER_INFO, {},
                                        timeout=DEFAULT_CMD_TIMEOUT)

    async def find_blocks(self, matching: str, max_count: int = 100) -> dict:
        return await self._send_request(METHOD_FIND_BLOCKS, {
            "matching": matching,
            "max_count": max_count,
        }, timeout=DEFAULT_CMD_TIMEOUT)
