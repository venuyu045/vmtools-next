"""BlueMap API monitor — polls the map website to detect join/leave events,
track Folia region performance, player residences, and custom markers.

Players endpoint (fast): 5s poll → join/leave diff → Socket.IO + QQ notify.
Markers endpoint (slow): 60s poll → residence/region/marker caches.
Each online player is tagged with the residence and Folia region they're in.
"""
from __future__ import annotations

import asyncio
import re
import time
from typing import Optional

import httpx

from vmtools_next.config import get_config
from vmtools_next.data.db import sio
from vmtools_next.infra.logging import get_logger

logger = get_logger("bluemap")

# ── geometry helper ────────────────────────────────────────────────

def _point_in_polygon_2d(x: float, z: float, polygon: list[dict]) -> bool:
    """Ray-casting algorithm: check if (x,z) is inside a 2D polygon."""
    n = len(polygon)
    if n < 3:
        return False
    inside = False
    j = n - 1
    for i in range(n):
        xi = polygon[i]["x"]
        zi = polygon[i]["z"]
        xj = polygon[j]["x"]
        zj = polygon[j]["z"]
        if ((zi > z) != (zj > z)) and (x < (xj - xi) * (z - zi) / (zj - zi + 1e-12) + xi):
            inside = not inside
        j = i
    return inside


# ── bot player tracking ────────────────────────────────────────────

_bot_players: dict[str, str] = {}
_suppress_join: set[str] = set()


def register_bot_player(mc_username: str, instance_name: str) -> None:
    if mc_username:
        _bot_players[mc_username] = instance_name


def unregister_bot_player(mc_username: str) -> None:
    if mc_username:
        _bot_players.pop(mc_username, None)
        _suppress_join.discard(mc_username)


def suppress_next_join(mc_username: str) -> None:
    if mc_username:
        _suppress_join.add(mc_username)


# ── monitor class ──────────────────────────────────────────────────

class BlueMapMonitor:
    """Background service that polls BlueMap API for players, regions, residences."""

    def __init__(self) -> None:
        self._task: Optional[asyncio.Task[None]] = None
        self._markers_task: Optional[asyncio.Task[None]] = None
        self._previous_players: dict[str, dict] = {}
        self._running = False

        # Cached marker data (refreshed every 60s)
        self._residences: list[dict] = []
        self._regions: list[dict] = []
        self._markers: list[dict] = []

    # ── lifecycle ──────────────────────────────────────────────────

    async def start(self) -> None:
        cfg = get_config().bluemap
        if not cfg.enabled:
            logger.info("BlueMap monitor disabled, skipping")
            return

        self._running = True

        # Load cached data from DB first (survives restarts)
        self._load_cache_from_db()

        self._task = asyncio.create_task(self._players_poll_loop())
        self._markers_task = asyncio.create_task(self._markers_poll_loop())

        await self._recover_bot_players()

        # Do an immediate markers poll so the frontend has data right away
        if not self._residences or not self._markers:
            logger.info("BlueMap: running initial markers poll...")
            await self._poll_markers_once()

        logger.info(
            "BlueMap monitor started (players={}s, markers=60s, base_url={}, worlds={})",
            cfg.poll_interval_seconds,
            cfg.api_base_url,
            cfg.worlds,
        )

    async def stop(self) -> None:
        self._running = False
        for t in (self._task, self._markers_task):
            if t:
                t.cancel()
                try:
                    await t
                except asyncio.CancelledError:
                    pass
        self._task = None
        self._markers_task = None
        logger.info("BlueMap monitor stopped")

    # ── players poll (fast) ─────────────────────────────────────────

    async def _players_poll_loop(self) -> None:
        cfg = get_config().bluemap
        while self._running:
            try:
                await self._poll_players_once()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.warning("BlueMap players poll error: {}", exc)
            await asyncio.sleep(cfg.poll_interval_seconds)

    async def _poll_players_once(self) -> None:
        cfg = get_config().bluemap
        all_players: dict[str, dict] = {}

        async with httpx.AsyncClient(timeout=httpx.Timeout(10.0)) as client:
            for world in cfg.worlds:
                try:
                    url = f"{cfg.api_base_url}/maps/{world}/live/players.json"
                    resp = await client.get(url)
                    if resp.status_code != 200:
                        continue
                    data = resp.json()
                    for p in data.get("players", []):
                        if p.get("foreign", False):
                            continue
                        name = p["name"]
                        if name in all_players:
                            continue
                        pos = p.get("position", {})
                        player = {
                            "name": name,
                            "uuid": p["uuid"],
                            "world": world,
                            "foreign": p.get("foreign", False),
                            "position": pos,
                            "rotation": p.get("rotation"),
                        }
                        # Tag with residence & region
                        if pos:
                            player["residence"] = self._find_residence(pos.get("x", 0), pos.get("y", 0), pos.get("z", 0))
                            player["region"] = self._find_region(pos.get("x", 0), pos.get("z", 0))
                        else:
                            player["residence"] = None
                            player["region"] = None
                        all_players[name] = player
                except Exception:
                    pass

        current_names = set(all_players.keys())
        previous_names = set(self._previous_players.keys())
        joined = current_names - previous_names
        left = previous_names - current_names

        # Full list
        player_list = [
            {
                "name": p["name"], "uuid": p["uuid"], "world": p["world"],
                "foreign": p["foreign"], "position": p["position"],
                "rotation": p["rotation"],
                "residence": p.get("residence"),
                "region": p.get("region"),
            }
            for p in all_players.values()
        ]
        await sio.emit("online_players_update", {
            "players": player_list,
            "count": len(player_list),
            "timestamp": time.time(),
        })

        # Individual events
        for name in joined:
            p = all_players[name]
            logger.info("Player joined: {} (world={})", name, p["world"])
            await sio.emit("player_event", {
                "name": name, "event": "join", "world": p["world"],
                "position": p["position"],
                "residence": p.get("residence"),
                "region": p.get("region"),
            })
            await self._notify_tracked(name, "join")
            await self._notify_bot_player(name, "join")

        for name in left:
            logger.info("Player left: {}", name)
            await sio.emit("player_event", {"name": name, "event": "leave"})
            await self._notify_tracked(name, "leave")
            await self._notify_bot_player(name, "leave")

        self._previous_players = all_players

    # ── markers poll (slow, 60s) ────────────────────────────────────

    async def _markers_poll_loop(self) -> None:
        while self._running:
            try:
                await self._poll_markers_once()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.warning("BlueMap markers poll error: {}", exc)
            await asyncio.sleep(60)

    async def _poll_markers_once(self) -> None:
        cfg = get_config().bluemap
        url = f"{cfg.api_base_url}/maps/world/live/markers.json"

        async with httpx.AsyncClient(timeout=httpx.Timeout(15.0)) as client:
            try:
                resp = await client.get(url)
                if resp.status_code != 200:
                    return
                data = resp.json()
            except Exception:
                return

        # Parse residences
        residences: list[dict] = []
        res_markers = data.get("Residences", {}).get("markers", {})
        for key, mk in res_markers.items():
            owner = ""
            m = re.search(r"所有者:.*?>(.+?)<", mk.get("detail", ""))
            if m:
                owner = m.group(1)
            shape = mk.get("shape", [])
            area = self._polygon_area(shape) if len(shape) >= 3 else 0
            residences.append({
                "id": key,
                "label": mk.get("label", key),
                "owner": owner,
                "min_y": mk.get("shapeMinY", 0),
                "max_y": mk.get("shapeMaxY", 0),
                "shape": shape,
                "area": round(area, 1),
                "position": mk.get("position"),
                "type": mk.get("type", ""),
            })

        # Parse folia regions
        regions: list[dict] = []
        folia = data.get("folia-regions", {}).get("markers", {})
        for key, mk in folia.items():
            detail = mk.get("detail", "")
            tps = _extract_float(detail, r"TPS:\s*([\d.]+)")
            mspt = _extract_float(detail, r"MSPT:\s*([\d.]+)")
            entities = _extract_int(detail, r"Entities:\s*(\d+)")
            players = _extract_int(detail, r"Players:\s*(\d+)")
            chunks = _extract_int(detail, r"Chunks:\s*(\d+)")
            sections = _extract_int(detail, r"Sections:\s*(\d+)")
            regions.append({
                "id": key,
                "label": mk.get("label", key),
                "shape": mk.get("shape", []),
                "shape_y": mk.get("shapeY", 0),
                "tps": tps,
                "mspt": mspt,
                "entities": entities,
                "players_in_region": players,
                "chunks": chunks,
                "sections": sections,
                "position": mk.get("position"),
            })

        # Parse custom markers
        markers: list[dict] = []
        mk_group = data.get("markers", {}).get("markers", {})
        for key, mk in mk_group.items():
            markers.append({
                "id": key,
                "label": mk.get("label", key),
                "position": mk.get("position"),
                "type": mk.get("type", ""),
                "detail": _strip_html(mk.get("detail", ""))[:200],
            })

        self._residences = residences
        self._regions = regions
        self._markers = markers
        logger.info(
            "BlueMap markers refreshed: {} residences, {} regions, {} markers",
            len(residences), len(regions), len(markers),
        )

        # Save to DB for persistence across restarts
        self._save_cache_to_db()

        # Push to clients
        await sio.emit("regions_update", {"regions": regions, "timestamp": time.time()})
        await sio.emit("residences_update", {"residences": residences, "timestamp": time.time()})
        await sio.emit("markers_update", {"markers": markers, "timestamp": time.time()})

    # ── DB cache persistence ─────────────────────────────────────────

    def _save_cache_to_db(self) -> None:
        """Save current residences/regions/markers to DB for persistence."""
        try:
            import json as _json
            from vmtools_next.data.db import get_session_factory
            Session = get_session_factory()
            db = Session()
            try:
                now = time.time()
                for key, data in [
                    ("bluemap_residences", self._residences),
                    ("bluemap_regions", self._regions),
                    ("bluemap_markers", self._markers),
                ]:
                    db.execute(
                        db.execute.__self__ if hasattr(db, 'execute') else None
                    )
                # Use raw SQL for simplicity since we don't have a model
                from sqlalchemy import text
                for key, data in [
                    ("bluemap_residences", self._residences),
                    ("bluemap_regions", self._regions),
                    ("bluemap_markers", self._markers),
                ]:
                    payload = _json.dumps(data, ensure_ascii=False)
                    db.execute(
                        text(
                            "INSERT INTO bluemap_cache (cache_key, cache_data, updated_at) "
                            "VALUES (:key, :data, :ts) "
                            "ON CONFLICT(cache_key) DO UPDATE SET cache_data=:data2, updated_at=:ts2"
                        ),
                        {"key": key, "data": payload, "ts": now, "data2": payload, "ts2": now},
                    )
                db.commit()
            finally:
                db.close()
        except Exception as exc:
            logger.debug("BlueMap DB cache save failed: {}", exc)

    def _load_cache_from_db(self) -> None:
        """Load cached residences/regions/markers from DB (survives restart)."""
        try:
            import json as _json
            from vmtools_next.data.db import get_session_factory
            from sqlalchemy import text
            Session = get_session_factory()
            db = Session()
            try:
                rows = db.execute(
                    text("SELECT cache_key, cache_data FROM bluemap_cache")
                ).fetchall()
                for row in rows:
                    key, payload = row[0], row[1]
                    data = _json.loads(payload) if payload else []
                    if key == "bluemap_residences":
                        self._residences = data
                    elif key == "bluemap_regions":
                        self._regions = data
                    elif key == "bluemap_markers":
                        self._markers = data
                if self._residences or self._markers:
                    logger.info(
                        "BlueMap: loaded cache from DB ({} residences, {} markers)",
                        len(self._residences), len(self._markers),
                    )
            finally:
                db.close()
        except Exception as exc:
            logger.debug("BlueMap DB cache load failed (table may not exist yet): {}", exc)

    # ── spatial lookup ──────────────────────────────────────────────

    def _find_residence(self, x: float, y: float, z: float) -> Optional[dict]:
        for r in self._residences:
            if y < r["min_y"] or y > r["max_y"]:
                continue
            if _point_in_polygon_2d(x, z, r["shape"]):
                return {"name": r["label"], "owner": r["owner"], "area": r["area"]}
        return None

    def _find_region(self, x: float, z: float) -> Optional[dict]:
        for r in self._regions:
            if _point_in_polygon_2d(x, z, r["shape"]):
                return {
                    "label": r["label"], "tps": r["tps"], "mspt": r["mspt"],
                    "entities": r["entities"], "players_in_region": r["players_in_region"],
                    "chunks": r["chunks"], "sections": r["sections"],
                }
        return None

    @staticmethod
    def _polygon_area(shape: list[dict]) -> float:
        """Shoelace formula for polygon area (approximate, in blocks²)."""
        n = len(shape)
        if n < 3:
            return 0.0
        area = 0.0
        j = n - 1
        for i in range(n):
            area += (shape[j]["x"] + shape[i]["x"]) * (shape[j]["z"] - shape[i]["z"])
            j = i
        return abs(area) / 2.0

    # ── QQ notification ────────────────────────────────────────────

    async def _notify_tracked(self, player_name: str, event_type: str) -> None:
        tracking = get_config().player_tracking
        if not tracking.enabled:
            return
        tracked: dict[str, str] = {}
        for owner in tracking.owners:
            for pname in owner.track_players:
                tracked[pname] = owner.qq_openid

        qq: Optional[str] = tracked.get(player_name)
        display = player_name
        if not qq:
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
        asyncio.ensure_future(broadcast(msg, mention_openids=[qq]))

    # ── bot player notifications ───────────────────────────────────

    async def _recover_bot_players(self) -> None:
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
        finally:
            db.close()

    async def _notify_bot_player(self, player_name: str, event_type: str) -> None:
        instance_name = _bot_players.get(player_name)
        if not instance_name:
            return
        if event_type == "join":
            if player_name in _suppress_join:
                _suppress_join.discard(player_name)
                return
            from vmtools_next.core.qqbot_notify import notify_instance_online
            asyncio.ensure_future(notify_instance_online(instance_name))
        else:
            from vmtools_next.core.qqbot_notify import notify_instance_offline
            asyncio.ensure_future(notify_instance_offline(instance_name))

    # ── public accessors (for API endpoints) ────────────────────────

    def get_regions(self) -> list[dict]:
        return self._regions

    def get_residences(self) -> list[dict]:
        return self._residences

    def get_markers(self) -> list[dict]:
        return self._markers


# ── helpers ────────────────────────────────────────────────────────

def _extract_float(text: str, pattern: str) -> Optional[float]:
    m = re.search(pattern, text)
    return float(m.group(1)) if m else None


def _extract_int(text: str, pattern: str) -> Optional[int]:
    m = re.search(pattern, text)
    return int(m.group(1)) if m else None


def _strip_html(text: str) -> str:
    return re.sub(r"<[^>]+>", "", text).strip()
