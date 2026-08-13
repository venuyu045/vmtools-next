"""Auto Super-AFK Plugin — bot 进入服务器后自动开启「超级省流挂机模式」(/afk super).

2026-08-13 实测服务器行为（sy.server.mangocraft.cn，芒果方块粉丝服）::

    /afk super  → 超级省流挂机模式，**需要二次确认**：
      第一次：⚠️ [进入确认] 您即将进入手动超级省流挂机模式！……
             若您确认要开启，请在 3 分钟内再次输入指令进行二次确认: /afk super
      第二次（3 分钟内）：⚠️ [超级省流模式已启用] 仅限挂机……
      再输入一次：您已退出超级省流模式！（退出后需重连以刷新区块）

超级省流模式**不跨登录保持**，且退出必须重进服务器才能刷新区块。
本插件在 bot_spawned 后自动发送 /afk super，并监听服务器消息：
  - 响应含「进入确认」→ 补发第二次完成二次确认
  - 响应含「已启用」  → 直接成功（无需再发）

配置（经 plugin_states 持久化）::

    {"apply_on_spawn": true, "delay_ms": 6000, "confirm_delay_ms": 6000}
"""
from __future__ import annotations

import asyncio
import re
from typing import Optional

from vmtools_next.infra.logging import get_logger
from vmtools_next.plugins.base import IPlugin, PluginContext

logger = get_logger("plugins.auto_afk_super")

STRIP_MOTD = re.compile(r"\u00a7.")


def _plain(text: str) -> str:
    """剥离 MC 格式码（§x）。"""
    return STRIP_MOTD.sub("", text or "")


class Plugin(IPlugin):
    """MF 自动开启超级省流挂机模式插件（/afk super，含二次确认）。"""

    name = "auto_afk_super"
    version = "1.0.0"
    engine = "mineflayer"
    description = "bot 进入服务器后自动输入 /afk super 开启超级省流挂机模式（自动完成二次确认）"

    default_config = {
        "apply_on_spawn": True,
        "delay_ms": 6000,          # 进入后延迟发送第一次
        "confirm_delay_ms": 6000,  # 收到「进入确认」后延迟补发第二次
    }

    def __init__(self) -> None:
        self._context: Optional[PluginContext] = None
        self._enabled = True
        self._apply_on_spawn = True
        self._delay_ms = 6000
        self._confirm_delay_ms = 6000
        self._tasks: dict[str, asyncio.Task] = {}
        self._pending_bots: set[str] = set()   # 已发送第一次、等待确认/响应

    async def load(self, context: PluginContext) -> None:
        self._context = context

    def apply_config(self, config: dict) -> None:
        cfg = config or {}
        self._apply_on_spawn = bool(cfg.get("apply_on_spawn", True))
        self._delay_ms = max(0, int(cfg.get("delay_ms", 6000)))
        self._confirm_delay_ms = max(0, int(cfg.get("confirm_delay_ms", 6000)))
        logger.info("auto_afk_super config applied (apply_on_spawn={}, delay_ms={}, confirm_delay_ms={})",
                    self._apply_on_spawn, self._delay_ms, self._confirm_delay_ms)

    async def start(self) -> None:
        self._enabled = True
        logger.info("auto_afk_super started")

    async def stop(self) -> None:
        self._enabled = False
        for task in self._tasks.values():
            task.cancel()
        self._tasks.clear()
        self._pending_bots.clear()

    async def reload(self) -> None:
        await self.load(self._context)

    async def on_event(self, event_type: str, payload: dict) -> None:
        if not self._enabled:
            return
        bot_id = payload.get("bot_id") or ""
        if not bot_id:
            return
        if event_type == "bot_spawned":
            if self._apply_on_spawn:
                self._schedule_send(bot_id, "/afk super", self._delay_ms, label="spawn-1st")
        elif event_type == "bot_message":
            msg = _plain(str(payload.get("message") or ""))
            if bot_id not in self._pending_bots:
                return
            if "进入确认" in msg:
                # 服务器要求二次确认 → 补发第二次
                self._pending_bots.discard(bot_id)
                logger.info("Bot {} 收到二次确认提示，补发 /afk super 完成开启", bot_id)
                self._schedule_send(bot_id, "/afk super", self._confirm_delay_ms, label="confirm-2nd")
            elif "已启用" in msg:
                self._pending_bots.discard(bot_id)
                logger.info("Bot {} 超级省流模式已启用", bot_id)

    def _schedule_send(self, bot_id: str, command: str, delay_ms: int, label: str) -> None:
        async def _run() -> None:
            try:
                await asyncio.sleep(delay_ms / 1000.0)
                if not self._enabled:
                    return
                client = self._context.pool.get_client(bot_id) if self._context else None
                if client is None or not client.is_connected:
                    logger.debug("Bot {} not connected, skip afk super apply ({})", bot_id, label)
                    return
                await client.send_chat(command)
                self._pending_bots.add(bot_id)
                logger.info("Bot {} sent {} ({})", bot_id, command, label)
            except asyncio.CancelledError:
                pass
            except Exception as exc:
                logger.warning("Bot {} afk super apply failed ({}): {}", bot_id, label, exc)
            finally:
                self._tasks.pop(bot_id, None)

        old = self._tasks.get(bot_id)
        if old and not old.done():
            old.cancel()
        self._tasks[bot_id] = asyncio.ensure_future(_run())