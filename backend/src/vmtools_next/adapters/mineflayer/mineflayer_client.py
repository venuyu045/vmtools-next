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
    METHOD_SET_CONTROL_STATE,
    METHOD_LOOK,
    METHOD_JUMP,
    METHOD_SNEAK,
    METHOD_PLACE_BLOCK,
    METHOD_DIG_BLOCK,
    METHOD_GET_WORLD_BLOCK_AT,
    METHOD_SCAN_NEARBY_BLOCKS,
    METHOD_SCAN_LOADED_CONTAINERS,
    METHOD_SELECT_HOTBAR_ITEM,
    METHOD_SET_QUICK_BAR_SLOT,
    METHOD_GET_INVENTORY_SNAPSHOT,
    METHOD_OPEN_CONTAINER_AT,
    METHOD_CLOSE_CONTAINER,
    METHOD_GET_CONTAINER_SNAPSHOT,
    METHOD_WITHDRAW_CONTAINER_ITEM,
    METHOD_DEPOSIT_CONTAINER_ITEM,
    METHOD_DROP_ITEM,
    METHOD_MOVE_ITEM,
    METHOD_USE_ITEM,
    METHOD_CLICK_WINDOW,
    METHOD_ACTIVATE_ITEM,
    METHOD_ACTIVATE_BLOCK,
    METHOD_GET_CURRENT_WINDOW,
    METHOD_EQUIP_OFFHAND,
    METHOD_CONSUME_OFFHAND,
    METHOD_SCAFFOLD_TO,
    METHOD_SERVUX_HANDSHAKE,
    METHOD_PREVIEW_CONTAINER_AT,
    METHOD_SEND_CHAT,
    METHOD_RUN_COMMAND,
    METHOD_GET_SERVER_INFO,
    METHOD_FIND_BLOCKS,
    METHOD_GET_NEARBY_ENTITIES,
    METHOD_ATTACK,
    METHOD_SET_AUTO_ATTACK,
    METHOD_SET_GUARD,
    METHOD_GET_COMBAT_STATUS,
    METHOD_STOP_COMBAT,
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
        self.host = host
        self.port = port
        self.connected_at: str | None = None
        self.last_heartbeat_at: str | None = None
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
            websockets.connect(
                self._ws_url,
                ping_interval=10,
                ping_timeout=5,
                max_size=64 * 1024 * 1024,   # 64MB：超大仓库容器发现（1.4万+坐标）单响应可能超默认1MB
                max_queue=256,
            ),
            timeout=timeout,
        )
            self._connected = True
            self._listen_task = asyncio.create_task(self._listen_loop())
            from datetime import datetime, timezone
            self.connected_at = datetime.now(timezone.utc).isoformat()
            self.last_heartbeat_at = self.connected_at
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
        # 收到状态推送即视为心跳，供 get_bot_status 的 last_heartbeat 使用
        from datetime import datetime, timezone
        self.last_heartbeat_at = datetime.now(timezone.utc).isoformat()
        logger.debug("Status update: connected=%s", status.get("connected"))
        # 状态推送分发到事件处理器（SessionPool 据此把坐标/血量/饱食度
        # 同步到 DB + Socket.IO，状态页才能显示 MF 实例的坐标与最近领地）
        for handler in list(self._event_handlers):
            try:
                result = handler("status", status)
                if asyncio.iscoroutine(result):
                    asyncio.create_task(result)
            except Exception as e:
                logger.warning("Event handler error for status: %s", e)

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

    async def scan_nearby_blocks(self, radius: int = 16, max_count: int = 500000,
                                  matching: str = None, box: dict = None) -> dict:
        params = {"radius": radius, "max_count": max_count}
        if matching:
            params["matching"] = matching
        if box:
            params.update({
                "box_min_x": box.get("min_x"), "box_max_x": box.get("max_x"),
                "box_min_y": box.get("min_y"), "box_max_y": box.get("max_y"),
                "box_min_z": box.get("min_z"), "box_max_z": box.get("max_z"),
            })
        return await self._send_request(METHOD_SCAN_NEARBY_BLOCKS, params,
                                        timeout=DEFAULT_CMD_TIMEOUT)

    async def scan_loaded_containers(self, max_count: int = 10000) -> dict:
        """扫描 bot 已加载区块内的全部容器方块（不受 ±15 格限制）。

        返回 {"success": bool, "count": int, "blocks": [{x, y, z, name, type}, ...]}
        """
        return await self._send_request(METHOD_SCAN_LOADED_CONTAINERS, {
            "max_count": max_count,
        }, timeout=30.0)

    async def open_container_at(self, x: int, y: int, z: int) -> dict:
        """前往（距离远自动寻路靠近）并打开容器，返回 container_id / slot_count / block_name。"""
        return await self._send_request(METHOD_OPEN_CONTAINER_AT, {
            "x": x, "y": y, "z": z,
        }, timeout=CONTAINER_TIMEOUT)

    async def get_container_snapshot(self, container_id: str) -> dict:
        """获取已打开容器的内容快照。"""
        return await self._send_request(METHOD_GET_CONTAINER_SNAPSHOT, {
            "container_id": container_id,
        }, timeout=DEFAULT_CMD_TIMEOUT)

    async def close_container(self, container_id: str) -> dict:
        """关闭指定容器。"""
        return await self._send_request(METHOD_CLOSE_CONTAINER, {
            "container_id": container_id,
        }, timeout=DEFAULT_CMD_TIMEOUT)

    # ── 移动 ──

    async def move_to(self, x: int, y: int, z: int,
                   max_offset: int = 3, timeout_ms: int = 15000,
                   ignore_y: bool = False) -> dict:
        return await self._send_request(METHOD_MOVE_TO, {
            "x": x, "y": y, "z": z,
            "max_offset": max_offset,
            "timeout_ms": timeout_ms,
            "ignore_y": ignore_y,
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

    # ── 战斗（自动攻击/手动攻击/守护，2026-08-10） ──
    async def get_nearby_entities(self, radius: int = 16,
                                  target_types: list[str] | None = None) -> dict:
        return await self._send_request(METHOD_GET_NEARBY_ENTITIES, {
            "radius": radius,
            "target_types": target_types or [],
        }, timeout=DEFAULT_CMD_TIMEOUT)

    async def attack(self, target_id: int | None = None,
                     target_type: str | None = None,
                     move_to_target: bool = False,
                     scan_radius: int = 16,
                     attack_radius: float = 3.0) -> dict:
        return await self._send_request(METHOD_ATTACK, {
            "target_id": target_id,
            "target_type": target_type,
            "move_to_target": move_to_target,
            "scan_radius": scan_radius,
            "attack_radius": attack_radius,
        }, timeout=DEFAULT_CMD_TIMEOUT)

    async def set_auto_attack(self, enabled: bool = True, radius: int = 8,
                              scan_radius: int | None = None,
                              attack_radius: float = 3.0,
                              target_types: list[str] | None = None,
                              interval_ms: int = 1000,
                              interval_tick: int | None = None,
                              interval_mode: str = "auto",
                              stop_durability: float = 0.1,
                              move_to_target: bool = False,
                              enable_sprint_attack: bool = True,
                              enable_jump_crit: bool = True,
                              enable_wtap: bool = True,
                              enable_stap: bool = True,
                              enable_strafe: bool = True,
                              anti_afk: bool = True,
                              anti_afk_interval_ms: int = 60000) -> dict:
        return await self._send_request(METHOD_SET_AUTO_ATTACK, {
            "enabled": enabled,
            "radius": radius,
            "scan_radius": scan_radius,
            "attack_radius": attack_radius,
            "target_types": target_types or [],
            "interval_ms": interval_ms,
            "interval_tick": interval_tick,
            "interval_mode": interval_mode,
            "stop_durability": stop_durability,
            "move_to_target": move_to_target,
            "enable_sprint_attack": enable_sprint_attack,
            "enable_jump_crit": enable_jump_crit,
            "enable_wtap": enable_wtap,
            "enable_stap": enable_stap,
            "enable_strafe": enable_strafe,
            "anti_afk": anti_afk,
            "anti_afk_interval_ms": anti_afk_interval_ms,
        }, timeout=DEFAULT_CMD_TIMEOUT)

    async def set_guard(self, enabled: bool = True, x: float | None = None,
                        y: float | None = None, z: float | None = None,
                        radius: int = 8, scan_radius: int | None = None,
                        attack_radius: float = 3.0,
                        target_types: list[str] | None = None,
                        interval_ms: int = 1000,
                        interval_tick: int | None = None,
                        interval_mode: str = "auto",
                        stop_durability: float = 0.1,
                        move_to_target: bool = False) -> dict:
        return await self._send_request(METHOD_SET_GUARD, {
            "enabled": enabled,
            "x": x, "y": y, "z": z,
            "radius": radius,
            "scan_radius": scan_radius,
            "attack_radius": attack_radius,
            "target_types": target_types or [],
            "interval_ms": interval_ms,
            "interval_tick": interval_tick,
            "interval_mode": interval_mode,
            "stop_durability": stop_durability,
            "move_to_target": move_to_target,
        }, timeout=DEFAULT_CMD_TIMEOUT)

    async def get_combat_status(self) -> dict:
        return await self._send_request(METHOD_GET_COMBAT_STATUS, {},
                                        timeout=DEFAULT_CMD_TIMEOUT)

    async def stop_combat(self) -> dict:
        return await self._send_request(METHOD_STOP_COMBAT, {},
                                        timeout=5.0)

    # ── 玩家操控（背包页移动控制台：前后左右/跳跃/蹲下/视角） ──

    async def set_control_state(self, control: str, state: bool = True) -> dict:
        """持续按住/松开某个控制键（forward/back/left/right/jump/sneak/sprint）。"""
        return await self._send_request(METHOD_SET_CONTROL_STATE, {
            "control": control,
            "state": bool(state),
        }, timeout=DEFAULT_CMD_TIMEOUT)

    async def look(self, yaw: float, pitch: float | None = None, force: bool = False) -> dict:
        """视角控制：平滑转向（yaw/pitch 弧度；force=false 客户端平滑转向）。"""
        params: dict[str, Any] = {"yaw": yaw, "force": force}
        if pitch is not None:
            params["pitch"] = pitch
        return await self._send_request(METHOD_LOOK, params, timeout=DEFAULT_CMD_TIMEOUT)

    async def jump(self) -> dict:
        """跳跃一次。"""
        return await self._send_request(METHOD_JUMP, {}, timeout=DEFAULT_CMD_TIMEOUT)

    async def sneak(self, state: bool | None = None) -> dict:
        """蹲下/站起（state=None 时切换）。"""
        params: dict[str, Any] = {}
        if state is not None:
            params["state"] = bool(state)
        return await self._send_request(METHOD_SNEAK, params, timeout=DEFAULT_CMD_TIMEOUT)

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
                # type 在 mineflayer 里是数字 ID（int），name 才是字符串 ID——
                # 优先取 name/itemId，type 兜底并 str() 化，避免 int.strip() 崩（MF 背包接口 500）
                raw_id = s.get("name") or s.get("itemId") or s.get("type") or ""
                item_id = str(raw_id).strip()
                if not item_id:
                    continue
                # mineflayer 玩家窗口槽位：5-8=盔甲、9-35=主背包、36-44=快捷栏、45=副手、0-4=合成；
                # 统一归一化为前端标准布局（0-8 快捷栏、9-35 主背包、36-39 盔甲、40 副手、41-45 合成）。
                # 注意：归一化只在本客户端做一次，下游（mcc_bot）不得再转换，避免二次映射错位。
                _slot = s.get("slot", -1)
                if isinstance(_slot, int):
                    if 5 <= _slot <= 8:
                        _slot += 31            # 盔甲 5-8 → 36-39
                    elif 36 <= _slot <= 44:
                        _slot -= 36            # 快捷栏 36-44 → 0-8
                    elif _slot == 45:
                        _slot = 40             # 副手 → 40
                    elif 0 <= _slot <= 4:
                        _slot += 41            # 合成 0-4 → 41-45
                items.append({
                    "slot": _slot,
                    "type": item_id,
                    "displayName": s.get("displayName") or s.get("display_name") or item_id,
                    "count": s.get("count", s.get("amount", 0)) or 0,
                    "maxStackSize": s.get("max_stack_size", s.get("maxStackSize", 64)),
                    # 物品详情（前端「物品详情」弹窗）：耐久/附魔
                    "durability": s.get("durability"),
                    "maxDurability": s.get("max_durability", s.get("maxDurability")),
                    "enchantments": s.get("enchantments") or [],
                    # 自定义名 / Lore（2026-08-12）：Node 端解析后透传，勿删！
                    "custom_name": s.get("custom_name"),
                    "lore": s.get("lore"),
                    "debug": s.get("debug"),  # 诊断（结构确认后可移除）
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

    # ── 背包管理（与 MCC /mcc-bots/{id}/inventory 系列接口对齐） ──

    async def drop_inventory_item(self, item_type: str, count: int = 64,
                                  inventory_id: int = 0, slot_id: int | None = None) -> dict:
        """丢弃背包中的物品（MF: bot.toss/tossStack；inventory_id 仅为兼容 MCC 接口签名）。

        slot_id 为前端标准槽位（可选）：指定时精确丢弃该槽位（修复按类型全局
        findItemRange 找第一个槽位导致丢错槽位的问题）；不指定时按类型全局丢弃。
        """
        params: dict[str, Any] = {
            "item_type": item_type,
            "count": count,
        }
        if slot_id is not None:
            params["slot"] = self._frontend_to_node_slot(slot_id)
        return await self._send_request(METHOD_DROP_ITEM, params,
                                        timeout=DEFAULT_CMD_TIMEOUT)

    async def change_hotbar_slot(self, slot_index: int) -> dict:
        """切换快捷栏槽位（与 MCC select-hotbar 接口对齐）。"""
        return await self.set_quick_bar_slot(slot_index)

    async def inventory_window_action(self, inventory_id: int, slot_id: int,
                                      action_type: str) -> dict:
        """mineflayer 不支持通用窗口槽位点击（MCC 的 LeftClick/RightClick）——
        返回明确错误，避免前端 500。"""
        return {"success": False, "error": "mineflayer 不支持窗口槽位点击操作（仅支持查看背包 / 丢弃物品 / 切换快捷栏）"}

    # ── 前端标准槽位 → mineflayer 原始槽位（与 get_inventory_snapshot 归一化成对） ──
    # 前端标准布局：0-8=快捷栏、9-35=主背包、36-39=盔甲、40=副手、41-45=合成
    # mineflayer 原始布局：0-4=合成、5-8=盔甲、9-35=主背包、36-44=快捷栏、45=副手
    @staticmethod
    def _frontend_to_node_slot(slot: int) -> int:
        if not isinstance(slot, int):
            return slot
        if 0 <= slot <= 8:
            return slot + 36            # 快捷栏 0-8 → 36-44
        if 36 <= slot <= 39:
            return slot - 31            # 盔甲 36-39 → 5-8
        if slot == 40:
            return 45                   # 副手 40 → 45
        if 41 <= slot <= 45:
            return slot - 41            # 合成 41-45 → 0-4
        return slot                     # 主背包 9-35 → 9-35

    async def move_inventory_item(self, slot_id: int, dest_slot_id: int) -> dict:
        """移动/交换背包槽位（MF: bot.moveSlotItem，mineflayer 原生窗口点击）。

        slot_id / dest_slot_id 为前端标准槽位，此处转换为 mineflayer 原始槽位后下发。
        """
        src = self._frontend_to_node_slot(slot_id)
        dst = self._frontend_to_node_slot(dest_slot_id)
        return await self._send_request(METHOD_MOVE_ITEM, {
            "slot": src,
            "dest_slot": dst,
        }, timeout=DEFAULT_CMD_TIMEOUT)

    async def use_item(self, item_type: str | None = None, slot_id: int | None = None) -> dict:
        """使用物品（吃食物等）：自动装备到手持后 bot.consume() 食用。

        slot_id 为前端标准槽位（可选）；不传时按 item_type 全局查找；都不传则使用当前手持物品。
        """
        params: dict[str, Any] = {}
        if item_type:
            params["item_type"] = item_type
        if slot_id is not None:
            params["slot"] = self._frontend_to_node_slot(slot_id)
        return await self._send_request(METHOD_USE_ITEM, params,
                                        timeout=DEFAULT_CMD_TIMEOUT)

    # ── 窗口内点击 / 右键使用（2026-08-12，快捷潜影盒等） ──

    async def click_window(self, target: str = "inventory", slot: int = 0,
                           mouse_button: int = 0, mode: int = 0,
                           container_id: str | None = None) -> dict:
        """窗口内左键/右键物品（mineflayer 原生 clickWindow）。

        target="inventory"：玩家背包（slot 为前端标准槽位，此处映射为原始槽位）；
        target="container"：已打开容器（slot 为窗口内槽位，原样透传）。
        mouse_button：0=左键（拿/放整组） 1=右键（拿/放半组）。
        若服务器因点击打开新容器窗口（快捷潜影盒）→ 返回 new_container_id。
        """
        params: dict[str, Any] = {
            "target": target,
            "slot": (self._frontend_to_node_slot(slot)
                     if target == "inventory" else slot),
            "mouse_button": int(mouse_button),
            "mode": int(mode),
        }
        if container_id:
            params["container_id"] = container_id
        return await self._send_request(METHOD_CLICK_WINDOW, params,
                                        timeout=DEFAULT_CMD_TIMEOUT)

    async def activate_item(self) -> dict:
        """右键使用手持物品（快捷潜影盒/末影珍珠等；需先设为手持）。

        若服务器弹出新容器窗口 → 返回 new_container_id。
        """
        return await self._send_request(METHOD_ACTIVATE_ITEM, {},
                                        timeout=DEFAULT_CMD_TIMEOUT)

    async def activate_block(self, x: int, y: int, z: int) -> dict:
        """右键方块（箱子 UI / 快捷潜影盒方块触发等，2026-08-12）。

        距离远自动寻路靠近后右键；服务器插件弹出 GUI → 返回 new_container_id。
        """
        return await self._send_request(METHOD_ACTIVATE_BLOCK, {
            "x": x, "y": y, "z": z,
        }, timeout=DEFAULT_CMD_TIMEOUT)

    async def get_current_window(self) -> dict:
        """查询当前打开的窗口（2026-08-12）。

        已注册容器 → 返回 container_id / slot_count / items 快照（含自定义名/Lore）；
        未打开 → opened=false。前端挂载时轮询实现「常驻容器面板」。
        """
        return await self._send_request(METHOD_GET_CURRENT_WINDOW, {},
                                        timeout=DEFAULT_CMD_TIMEOUT)

    async def equip_offhand(self, item_type: str) -> dict:
        """装备物品到副手（2026-08-14 模块A：猪排等食物放副手 slot 45）。

        从背包任意位置找 item_type 并装备到副手。
        """
        return await self._send_request(METHOD_EQUIP_OFFHAND, {
            "item_type": item_type,
        }, timeout=DEFAULT_CMD_TIMEOUT)

    async def consume_offhand(self) -> dict:
        """吃副手食物（2026-08-14 模块A：主手拿方块时按住右键吃副手猪排）。

        副手无可食用物品 → 返回 success=false（后端据此触发食物补货）。
        """
        return await self._send_request(METHOD_CONSUME_OFFHAND, {},
                                        timeout=DEFAULT_CMD_TIMEOUT)

    async def scaffold_to(self, x: int, y: int, z: int,
                          timeout_ms: int = 30000) -> dict:
        """自动蹲搭搭路前往 (x,y,z)（2026-08-14：pathfinder 不可达时的兜底）。

        用手头方块搭柱/搭桥，蹲下走过去，直到水平到达目标。
        """
        return await self._send_request(METHOD_SCAFFOLD_TO, {
            "x": x, "y": y, "z": z, "timeout_ms": timeout_ms,
        }, timeout=timeout_ms / 1000 + 5.0)

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
