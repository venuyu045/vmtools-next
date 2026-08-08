"""QQ Bot notification service — forwards MCC events to configured QQ groups."""
from __future__ import annotations

import asyncio
from typing import Optional

from vmtools_next.adapters.qqbot import QqBotClient
from vmtools_next.config import get_config
from vmtools_next.infra.logging import get_logger

logger = get_logger("qqbot.notify")

_qq_client: Optional[QqBotClient] = None
_broadcast_task: Optional[asyncio.Task] = None


async def start() -> bool:
    """Start QQ Bot notification service. Returns True if started."""
    global _qq_client
    config = get_config().qqbot
    if not config.enabled or not config.app_id:
        return False
    if not config.notify_groups:
        logger.info("QQ Bot enabled but no notify_groups configured, skipping")
        return False

    _qq_client = QqBotClient(
        app_id=config.app_id,
        app_secret=config.app_secret,
        sandbox=config.sandbox,
    )
    ok = await _qq_client.start()
    if ok:
        logger.info("QQ Bot notification service started, groups={}", config.notify_groups)
        # Send startup notification
        await broadcast("VMTools Next 后端 上线了喵")
        # Start WebSocket listener for @bot commands (e.g., /list)
        await _qq_client.start_ws_listener()
    return ok


async def stop():
    """Stop QQ Bot notification service."""
    global _qq_client, _broadcast_task
    config = get_config().qqbot
    if _qq_client and _broadcast_task is None:
        await broadcast("VMTools Next 后端 下线了喵")
    if _qq_client:
        await _qq_client.stop()
        _qq_client = None
    if _broadcast_task:
        _broadcast_task.cancel()
        _broadcast_task = None
    logger.info("QQ Bot notification service stopped")


async def broadcast(message: str, mention_openids: list[str] | None = None) -> None:
    """Send a message to all configured QQ groups.

    Args:
        message: Message text
        mention_openids: List of QQ openids to @mention in the message.
            If None, uses config.mention_openids.
    """
    if not _qq_client:
        return
    config = get_config().qqbot
    targets = mention_openids if mention_openids is not None else config.mention_openids

    for group_id in config.notify_groups:
        try:
            await _qq_client.send_group_message(group_id, message, mention_openids=targets)
        except Exception as exc:
            logger.warning("QQ broadcast failed for group {}: {}", group_id, exc)


async def notify_mcc_event(
    instance_name: str,
    event: str,  # "running", "started", "stopped", "crashed"
    extra: str = "",
) -> None:
    """Send MCC instance status change to QQ groups."""
    config = get_config().qqbot
    if not config.enabled:
        return

    labels = {
        "running": "上线了喵",
        "started": "上线了喵",
        "stopped": "下线了喵",
        "crashed": "似了喵",
        "error": "出错了喵",
    }
    label = labels.get(event, event)

    msg = f"[{instance_name}] {label}"
    if extra:
        msg = f"[{instance_name}] {extra}"
    await broadcast(msg)


async def notify_mcc_chat(instance_name: str, player: str, message: str) -> None:
    """Forward game chat to QQ groups."""
    config = get_config().qqbot
    if not config.enabled or not config.notify_on_chat:
        return
    await broadcast(f"[{instance_name}] {player}: {message}")


# ── Auto-reconnect notifications ──────────────────────────────────

async def notify_reconnect_started(instance_name: str) -> None:
    """Notify that auto-reconnect has started after a disconnect."""
    config = get_config().qqbot
    if not config.enabled:
        return
    await broadcast(f"[{instance_name}] 自动重连已启动")


async def notify_reconnect_success(instance_name: str) -> None:
    """Notify that auto-reconnect succeeded (bot confirmed joined server)."""
    config = get_config().qqbot
    if not config.enabled:
        return
    await broadcast(f"[{instance_name}] 已成功重连")


# ── Server-detected online/offline notifications ──────────────────

async def notify_instance_online(instance_name: str) -> None:
    """Notify that instance went online (detected via BlueMap API)."""
    config = get_config().qqbot
    if not config.enabled:
        return
    await broadcast(f"[{instance_name}] 上线了喵")


async def notify_instance_offline(instance_name: str) -> None:
    """Notify that instance went offline (detected via BlueMap API)."""
    config = get_config().qqbot
    if not config.enabled:
        return
    await broadcast(f"[{instance_name}] 下线了喵")
