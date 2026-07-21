"""BlueMap API player monitor — polls the map website to detect join/leave events.

Replaces the terminal-output-based player detection (sentinel bot) with
HTTP polling of BlueMap's live players.json endpoint.

Keeps a diff of player sets across polls to emit join/leave events,
and notifies QQ for tracked players.
"""
from __future__ import annotations

import asyncio
import time
from typing import Optional

import httpx

from vmtools_next.config import get_config
from vmtools_next.data.db import sio
from vmtools_next.infra.logging import get_logger

logger = get_logger("bluemap")

# ── Bot player tracking ────────────────────────────────────────────
# Maps mc_username → instance_name for MCC bot instances.
# BlueMap poll will send QQ notifications when tracked bots join/leave.
_bot_players: dict[str, str] = {}
# Bot usernames whose next join notification should be suppressed
# (e.g. because auto-reconnect already sent "已成功重连")
_suppress_join: set[str] = set()


def register_bot_player(mc_username: str, instance_name: str) -> None:
    """Register a bot player for join/leave tracking."""
    if mc_username:
        _bot_players[mc_username] = instance_name
        logger.debug("Bot player registered: {} -> {}", mc_username, instance_name)


def unregister_bot_player(mc_username: str) -> None:
    """Unregister a bot player from tracking."""
    if mc_username:
        _bot_players.pop(mc_username, None)
        _suppress_join.discard(mc_username)
        logger.debug("Bot player unregistered: {}", mc_username)


def suppress_next_join(mc_username: str) -> None:
    """Suppress the next join notification for this bot (used after auto-reconnect)."""
    if mc_username:
        _suppress_join.add(mc_username)


class BlueMapMonitor:
    """Background service that polls BlueMap API for online players."""

    def __init__(self) -> None:
        self._task: Optional[asyncio.Task[None]] = None
        self._previous_players: dict[str, dict] = {}  # name -> player info
        self._running = False

    # ── lifecycle ────────────────────────────────────────────────────

    async def start(self) -> None:
        cfg = get_config().bluemap
        if not cfg.enabled:
            logger.info("BlueMap monitor disabled, skipping")
            return

        self._running = True
        self._task = asyncio.create_task(self._poll_loop())

        # Re-register bot players from running instances (recover after restart)
        await self._recover_bot_players()

        logger.info(
            "BlueMap monitor started (interval={}s, base_url={}, worlds={})",
            cfg.poll_interval_seconds,
            cfg.api_base_url,
            cfg.worlds,
        )

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info("BlueMap monitor stopped")

    # ── poll loop ────────────────────────────────────────────────────

    async def _poll_loop(self) -> None:
        cfg = get_config().bluemap
        while self._running:
            try:
                await self._poll_once()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.warning("BlueMap poll error: {}", exc)

            await asyncio.sleep(cfg.poll_interval_seconds)

    async def _poll_once(self) -> None:
        """Query all worlds, diff player sets, emit events."""
        cfg = get_config().bluemap
        all_players: dict[str, dict] = {}

        async with httpx.AsyncClient(timeout=httpx.Timeout(10.0)) as client:
            for world in cfg.worlds:
                try:
                    url = f"{cfg.api_base_url}/maps/{world}/live/players.json"
                    resp = await client.get(url)
                    if resp.status_code != 200:
                        logger.debug("BlueMap {} returned {}", world, resp.status_code)
                        continue
                    data = resp.json()
                    for p in data.get("players", []):
                        name = p["name"]
                        # Only record player from the world they're actually in,
                        # not from foreign (cross-dimension) listings
                        if p.get("foreign", False):
                            continue
                        # Use first-seen world if player already recorded (dedup)
                        if name in all_players:
                            continue
                        all_players[name] = {
                            "name": name,
                            "uuid": p["uuid"],
                            "world": world,
                            "foreign": p.get("foreign", False),
                            "position": p.get("position"),
                            "rotation": p.get("rotation"),
                        }
                except Exception as exc:
                    logger.debug("BlueMap fetch failed for world {}: {}", world, exc)

        current_names = set(all_players.keys())
        previous_names = set(self._previous_players.keys())

        joined = current_names - previous_names
        left = previous_names - current_names

        # ── emit full online player list ──
        player_list = [
            {
                "name": p["name"],
                "uuid": p["uuid"],
                "world": p["world"],
                "foreign": p["foreign"],
                "position": p["position"],
                "rotation": p["rotation"],
            }
            for p in all_players.values()
        ]
        await sio.emit("online_players_update", {
            "players": player_list,
            "count": len(player_list),
            "timestamp": time.time(),
        })

        # ── emit individual join/leave events ──
        for name in joined:
            player = all_players[name]
            logger.info("Player joined: {} (world={})", name, player["world"])
            await sio.emit("player_event", {
                "name": name,
                "event": "join",
                "world": player["world"],
                "position": player["position"],
            })
            await self._notify_tracked(name, "join")
            await self._notify_bot_player(name, "join")

        for name in left:
            logger.info("Player left: {}", name)
            await sio.emit("player_event", {
                "name": name,
                "event": "leave",
            })
            await self._notify_tracked(name, "leave")
            await self._notify_bot_player(name, "leave")

        self._previous_players = all_players

    # ── QQ notification ─────────────────────────────────────────────

    async def _notify_tracked(self, player_name: str, event_type: str) -> None:
        """Send QQ notification if this player is on the tracking list."""
        tracking = get_config().player_tracking
        if not tracking.enabled:
            return

        # Build lookup: tracked_player_name → qq_openid
        tracked: dict[str, str] = {}
        for owner in tracking.owners:
            for pname in owner.track_players:
                tracked[pname] = owner.qq_openid

        # Direct match first
        qq: Optional[str] = tracked.get(player_name)
        display = player_name
        if not qq:
            # Partial match: config says "Venus_Yu" but game shows "Venus_Yu002"
            for tname, tqq in tracked.items():
                if tname in player_name:
                    qq = tqq
                    display = tname
                    break

        if not qq:
            return

        from vmtools_next.core.qqbot_notify import broadcast

        label = "离线了喵" if event_type == "leave" else "上线了喵"
        msg = f"{display} {label}"
        logger.info("Tracked player event: {} {} -> QQ {}", player_name, event_type, qq)
        asyncio.ensure_future(broadcast(msg, mention_openids=[qq]))

    # ── Bot player notifications ─────────────────────────────────────

    async def _recover_bot_players(self) -> None:
        """Re-register bot players from all running/started instances (recover after restart)."""
        from vmtools_next.data.db import get_session_factory
        from vmtools_next.data.models.mcc_remote import MccInstanceModel

        Session = get_session_factory()
        db = Session()
        try:
            instances = db.query(MccInstanceModel).filter(
                MccInstanceModel.deleted_at.is_(None),
                MccInstanceModel.mc_username.isnot(None),
                MccInstanceModel.mc_username != "",
                MccInstanceModel.status.in_(["running", "starting", "started"]),
            ).all()
            for inst in instances:
                name = inst.display_name or inst.slug
                register_bot_player(inst.mc_username, name)
                logger.info("BlueMap: recovered bot player {} -> {}", inst.mc_username, name)
            if instances:
                logger.info("BlueMap: recovered {} bot players from DB", len(instances))
        except Exception as exc:
            logger.warning("BlueMap: failed to recover bot players: {}", exc)
        finally:
            db.close()

    async def _notify_bot_player(self, player_name: str, event_type: str) -> None:
        """Send instance-level QQ notification when a tracked bot joins/leaves."""
        instance_name = _bot_players.get(player_name)
        if not instance_name:
            return

        if event_type == "join":
            if player_name in _suppress_join:
                _suppress_join.discard(player_name)
                logger.info("Bot join suppressed (auto-reconnect): {} -> {}", player_name, instance_name)
                return
            from vmtools_next.core.qqbot_notify import notify_instance_online
            _asyncio = __import__("asyncio")
            _asyncio.ensure_future(notify_instance_online(instance_name))
            logger.info("Bot online: {} -> {}", player_name, instance_name)
        else:
            from vmtools_next.core.qqbot_notify import notify_instance_offline
            _asyncio = __import__("asyncio")
            _asyncio.ensure_future(notify_instance_offline(instance_name))
            logger.info("Bot offline: {} -> {}", player_name, instance_name)
