"""Chat Responder Plugin — mineflayer bot 聊天指令自动响应.

仅服务 mineflayer 引擎（MCC 不需要额外插件）。
订阅 MF bot 的 ``bot_chat`` 事件（WS 桥接广播玩家聊天），当玩家在游戏内
发送以 ``!`` 开头的指令时，bot 通过 ``send_chat`` 自动回复。

事件负载（由 MineflayerSessionPool 注入 bot_id 后转发）::

    {"bot_id": "xxx", "username": "player", "message": "!pos"}

配置（config.yaml → plugins.builtin.chat_responder）::

    plugins:
      builtin:
        chat_responder:
          enabled: true
          commands:
            "!ping": "pong! ({username})"
            "!pos": "当前位置 {position}"
            "!help": "可用指令: !ping / !pos / !help"
"""
from __future__ import annotations

import logging
from typing import Any

from vmtools_next.plugins.base import IPlugin, PluginContext

logger = logging.getLogger("vmtools.plugins.chat_responder")

DEFAULT_COMMANDS: dict[str, str] = {
    "!ping": "pong! ({username})",
    "!pos": "当前位置 {position}",
    "!help": "可用指令: !ping / !pos / !help",
}


class Plugin(IPlugin):
    """MF 聊天指令响应插件（engine=mineflayer）。"""

    name = "chat_responder"
    version = "1.0.0"
    engine = "mineflayer"
    description = "MF bot 聊天指令自动响应（!ping / !pos / !help）"

    def __init__(self) -> None:
        self._context: PluginContext | None = None
        self._enabled = True
        self._commands: dict[str, str] = dict(DEFAULT_COMMANDS)

    async def load(self, context: PluginContext) -> None:
        self._context = context
        # 从配置读取指令表（可选覆盖）
        try:
            from vmtools_next.config import get_config
            cfg = get_config().plugins.builtin.chat_responder
            self._enabled = cfg.get("enabled", True)
            commands = cfg.get("commands")
            if isinstance(commands, dict) and commands:
                self._commands = {str(k): str(v) for k, v in commands.items()}
        except Exception as exc:  # 配置缺失时用默认值，不影响启动
            logger.debug("chat_responder config fallback: %s", exc)

    async def start(self) -> None:
        self._enabled = True
        logger.info("Chat responder started (commands=%s)", list(self._commands))

    async def stop(self) -> None:
        self._enabled = False

    async def reload(self) -> None:
        # 重新读取配置
        await self.load(self._context)
        logger.info("Chat responder reloaded")

    async def on_event(self, event_type: str, payload: dict) -> None:
        if not self._enabled:
            return
        if event_type != "bot_chat":
            return

        bot_id = payload.get("bot_id") or ""
        username = str(payload.get("username") or "player")
        message = str(payload.get("message") or "").strip()
        if not bot_id or not message or not message.startswith("!"):
            return

        cmd = message.split()[0].lower()
        template = self._commands.get(cmd)
        if not template:
            return

        reply = template
        if "{username}" in reply:
            reply = reply.replace("{username}", username)
        if "{position}" in reply:
            reply = reply.replace("{position}", await self._get_position(bot_id))

        await self._reply(bot_id, reply)

    async def _get_position(self, bot_id: str) -> str:
        """尝试通过 MF 桥接获取 bot 坐标；失败返回占位文本。"""
        try:
            if not self._context or not self._context.pool:
                return "?"
            client = self._context.pool.get_client(bot_id)
            if client is None or not client.is_connected:
                return "?"
            state = await client.get_player_state()
            pos = state.get("position") or state.get("pos")
            if isinstance(pos, dict):
                x = pos.get("x", 0)
                y = pos.get("y", 0)
                z = pos.get("z", 0)
                return f"({x}, {y}, {z})"
            return "?"
        except Exception as exc:
            logger.debug("Get position failed for %s: %s", bot_id, exc)
            return "?"

    async def _reply(self, bot_id: str, text: str) -> None:
        try:
            if not self._context or not self._context.pool:
                return
            client = self._context.pool.get_client(bot_id)
            if client is None or not client.is_connected:
                logger.debug("Bot %s not connected, skip reply", bot_id)
                return
            await client.send_chat(text)
            logger.info("Bot %s replied: %s", bot_id, text)
        except Exception as exc:
            logger.warning("Reply failed for %s: %s", bot_id, exc)
