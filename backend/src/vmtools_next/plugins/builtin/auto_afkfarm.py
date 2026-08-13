"""Auto AFK-farm Plugin — 自动保持服务器的「离线挂机保护」(/afkfarm).

2026-08-13 实测服务器行为（sy.server.mangocraft.cn，芒果方块粉丝服）::

    /afkfarm  → 开关「离线挂机保护」：
      开启：断开连接后自动生成挂机羊维持机器运转；羊维持 10 分钟，
            超时未上线羊被清理，**下次进入必须重新输入 /afkfarm**。
      关闭：已关闭离线挂机保护！

因此 bot 每次进入服务器后都应自动输入 /afkfarm 以保持保护开启。
本插件在 bot_spawned 后延迟发送 /afkfarm，并通过监听服务器消息
（bot_message 事件，Node 端 2026-08-13 新增广播）识别响应：
  - 响应「已启用」→ 保持开启，完成
  - 响应「已关闭」→ 说明登录时保护本就开着（挂机羊仍在），
    再补发一次恢复开启，确保最终状态 = 开启

配置（经 plugin_states 持久化）::

    {"apply_on_spawn": true, "delay_ms": 6000, "ensure_enabled": true}
"""
from __future__ import annotations

import asyncio
import re
from typing import Optional

from vmtools_next.infra.logging import get_logger
from vmtools_next.plugins.base import IPlugin, PluginContext

logger = get_logger("plugins.auto_afkfarm")

STRIP_MOTD = re.compile(r"\u00a7.")


def _plain(text: str) -> str:
    """剥离 MC 格式码（§x）。"""
    return STRIP_MOTD.sub("", text or "")


class Plugin(IPlugin):
    """MF 自动保持离线挂机保护插件（/afkfarm）。"""

    name = "auto_afkfarm"
    version = "1.0.0"
    engine = "mineflayer"
    description = "bot 进入服务器后自动输入 /afkfarm 保持离线挂机保护（挂机羊维持 10 分钟，超时需重进重输）"

    default_config = {
        "apply_on_spawn": True,   # bot 进入服务器后自动应用
        "delay_ms": 6000,         # 进入后延迟发送（等服务器加载完）
        "ensure_enabled": True,   # 响应为「已关闭」时补发一次，确保最终=开启
    }

    def __init__(self) -> None:
        self._context: Optional[PluginContext] = None
        self._enabled = True
        self._apply_on_spawn = True
        self._delay_ms = 6000
        self._ensure_enabled = True
        self._tasks: dict[str, asyncio.Task] = {}
        # 记录最近一次为该 bot 发送 /afkfarm 的时间（用于响应归属判断）
        self._pending_bots: set[str] = set()

    async def load(self, context: PluginContext) -> None:
        self._context = context

    def apply_config(self, config: dict) -> None:
        cfg = config or {}
        self._apply_on_spawn = bool(cfg.get("apply_on_spawn", True))
        self._delay_ms = max(0, int(cfg.get("delay_ms", 6000)))
        self._ensure_enabled = bool(cfg.get("ensure_enabled", True))
        logger.info("auto_afkfarm config applied (apply_on_spawn={}, delay_ms={}, ensure_enabled={})",
                    self._apply_on_spawn, self._delay_ms, self._ensure_enabled)

    async def start(self) -> None:
        self._enabled = True
        logger.info("auto_afkfarm started")

    async def stop(self) -> None:
        self._enabled = False
        for bot_id, task in list(self._tasks.items()):
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
                self._schedule_send(bot_id, "/afkfarm", self._delay_ms, label="spawn")
        elif event_type == "bot_message" and self._ensure_enabled:
            msg = _plain(str(payload.get("message") or ""))
            # 只处理本 bot 刚发过 /afkfarm 之后的响应
            if bot_id not in self._pending_bots:
                return
            if "已启用" in msg:
                self._pending_bots.discard(bot_id)
                logger.info("Bot {} 离线挂机保护已启用", bot_id)
            elif "已关闭" in msg:
                self._pending_bots.discard(bot_id)
                logger.info("Bot {} 登录时保护已开启（挂机羊仍在），补发 /afkfarm 恢复开启", bot_id)
                self._schedule_send(bot_id, "/afkfarm", 3000, label="re-enable")

    def _schedule_send(self, bot_id: str, command: str, delay_ms: int, label: str) -> None:
        async def _run() -> None:
            try:
                await asyncio.sleep(delay_ms / 1000.0)
                if not self._enabled:
                    return
                client = self._context.pool.get_client(bot_id) if self._context else None
                if client is None or not client.is_connected:
                    logger.debug("Bot {} not connected, skip afkfarm apply ({})", bot_id, label)
                    return
                await client.send_chat(command)
                self._pending_bots.add(bot_id)
                logger.info("Bot {} sent {} ({})", bot_id, command, label)
            except asyncio.CancelledError:
                pass
            except Exception as exc:
                logger.warning("Bot {} afkfarm apply failed ({}): {}", bot_id, label, exc)
            finally:
                self._tasks.pop(bot_id, None)

        old = self._tasks.get(bot_id)
        if old and not old.done():
            old.cancel()
        self._tasks[bot_id] = asyncio.ensure_future(_run())