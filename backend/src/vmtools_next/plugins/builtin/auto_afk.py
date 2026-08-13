"""Auto AFK Plugin — bot 进入服务器后自动进入手动 AFK 模式 (/afk).

2026-08-13 实测服务器行为（sy.server.mangocraft.cn，芒果方块粉丝服）::

    /afk  → 开关「手动 AFK 模式」：
      开启：ECO 节能模式已启用，数据更新可能会有延迟，TPSBAR 功能关闭；
            「您已进入手动 AFK 模式！再次输入/afk 退出此模式。」
      关闭：「您已退出手动 AFK 模式！」

手动 AFK 模式**不跨登录保持**（重进服务器需重新输入 /afk），
因此本插件在 bot_spawned 后自动发送 /afk 进入挂机状态。

配置（经 plugin_states 持久化）::

    {"apply_on_spawn": true, "delay_ms": 6000}
"""
from __future__ import annotations

import asyncio
from typing import Optional

from vmtools_next.infra.logging import get_logger
from vmtools_next.plugins.base import IPlugin, PluginContext

logger = get_logger("plugins.auto_afk")


class Plugin(IPlugin):
    """MF 自动进入手动 AFK 模式插件（/afk）。"""

    name = "auto_afk"
    version = "1.0.0"
    engine = "mineflayer"
    description = "bot 进入服务器后自动输入 /afk 进入手动 AFK 模式（ECO 节能，不跨登录保持）"

    default_config = {
        "apply_on_spawn": True,
        "delay_ms": 6000,
    }

    def __init__(self) -> None:
        self._context: Optional[PluginContext] = None
        self._enabled = True
        self._apply_on_spawn = True
        self._delay_ms = 6000
        self._tasks: dict[str, asyncio.Task] = {}

    async def load(self, context: PluginContext) -> None:
        self._context = context

    def apply_config(self, config: dict) -> None:
        cfg = config or {}
        self._apply_on_spawn = bool(cfg.get("apply_on_spawn", True))
        self._delay_ms = max(0, int(cfg.get("delay_ms", 6000)))
        logger.info("auto_afk config applied (apply_on_spawn={}, delay_ms={})",
                    self._apply_on_spawn, self._delay_ms)

    async def start(self) -> None:
        self._enabled = True
        logger.info("auto_afk started")

    async def stop(self) -> None:
        self._enabled = False
        for task in self._tasks.values():
            task.cancel()
        self._tasks.clear()

    async def reload(self) -> None:
        await self.load(self._context)

    async def on_event(self, event_type: str, payload: dict) -> None:
        if not self._enabled:
            return
        bot_id = payload.get("bot_id") or ""
        if not bot_id:
            return
        if event_type == "bot_spawned" and self._apply_on_spawn:
            self._schedule_send(bot_id, "/afk", self._delay_ms)

    def _schedule_send(self, bot_id: str, command: str, delay_ms: int) -> None:
        async def _run() -> None:
            try:
                await asyncio.sleep(delay_ms / 1000.0)
                if not self._enabled:
                    return
                client = self._context.pool.get_client(bot_id) if self._context else None
                if client is None or not client.is_connected:
                    logger.debug("Bot {} not connected, skip afk apply", bot_id)
                    return
                await client.send_chat(command)
                logger.info("Bot {} sent {} (spawn)", bot_id, command)
            except asyncio.CancelledError:
                pass
            except Exception as exc:
                logger.warning("Bot {} afk apply failed: {}", bot_id, exc)
            finally:
                self._tasks.pop(bot_id, None)

        old = self._tasks.get(bot_id)
        if old and not old.done():
            old.cancel()
        self._tasks[bot_id] = asyncio.ensure_future(_run())