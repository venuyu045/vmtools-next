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

    AFK_THRESHOLD_SECONDS = 600  # 10 minutes without movement → AFK

    # Leave debounce: a player must be missing for N consecutive polls before
    # we believe they actually left (BlueMap occasionally returns bogus data).
    LEAVE_CONFIRM_POLLS = 3        # normal leave: ~15s at 5s poll interval
    MASS_LEAVE_CONFIRM_POLLS = 24  # ALL players vanished at once → likely API glitch, ~2min

    def __init__(self) -> None:
        self._task: Optional[asyncio.Task[None]] = None
        self._markers_task: Optional[asyncio.Task[None]] = None
        self._previous_players: dict[str, dict] = {}
        self._miss_counts: dict[str, int] = {}  # name → consecutive polls missing
        self._running = False

        # AFK detection: {name: {x, y, z, last_moved_at, afk}}
        self._player_afk_status: dict[str, dict] = {}

        # Cached marker data (refreshed every 60s)
        self._residences: list[dict] = []
        self._regions: list[dict] = []
        self._markers: list[dict] = []
        # New BlueMap 5.16 marker sets
        self._landmarks: list[dict] = []       # mangopassport-landmarks (服务器地标)
        self._metro_lines: list[dict] = []     # folia-metro-lines (地铁线路)
        self._metro_stations: list[dict] = []  # folia-metro-stations (地铁站点)

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
        failed_worlds: set[str] = set()

        async with httpx.AsyncClient(timeout=httpx.Timeout(10.0)) as client:
            for world in cfg.worlds:
                try:
                    url = f"{cfg.api_base_url}/maps/{world}/live/players.json"
                    resp = await client.get(url)
                    if resp.status_code != 200:
                        failed_worlds.add(world)
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
                        # Tag with residence & region (scoped to the player's world —
                        # same coordinates in nether/end must not match overworld shapes)
                        if pos:
                            player["residence"] = self._find_residence(
                                pos.get("x", 0), pos.get("y", 0), pos.get("z", 0), world,
                            )
                            player["region"] = self._find_region(pos.get("x", 0), pos.get("z", 0), world)
                        else:
                            player["residence"] = None
                            player["region"] = None
                        all_players[name] = player
                except Exception:
                    failed_worlds.add(world)

        # All world requests failed → network/API outage, not players leaving.
        # Keep previous state untouched and skip the diff entirely.
        if len(failed_worlds) >= len(cfg.worlds):
            logger.warning(
                "BlueMap players poll: all {} world requests failed, skipping diff",
                len(cfg.worlds),
            )
            return

        previous = self._previous_players
        current_names = set(all_players.keys())
        joined = [n for n in current_names if n not in previous]
        missing = [n for n in previous if n not in current_names]

        # Mass-disappearance guard: BlueMap sometimes answers 200 with an
        # empty/bogus player list. If EVERY previously-online player vanished
        # in a single poll, require a much longer confirmation window.
        mass_glitch = len(previous) >= 2 and len(missing) == len(previous)
        threshold = self.MASS_LEAVE_CONFIRM_POLLS if mass_glitch else self.LEAVE_CONFIRM_POLLS
        if mass_glitch and not any(self._miss_counts.values()):
            logger.warning(
                "BlueMap: ALL {} players vanished in one poll — treating as "
                "possible API glitch, waiting {} polls before confirming",
                len(previous), threshold,
            )

        # Debounce leaves: only confirm after N consecutive missing polls.
        confirmed_left: list[str] = []
        for name in missing:
            last_world = previous[name].get("world")
            if last_world in failed_worlds:
                # That world's endpoint failed this round — no evidence of leaving.
                continue
            count = self._miss_counts.get(name, 0) + 1
            self._miss_counts[name] = count
            if count >= threshold:
                confirmed_left.append(name)

        # Players seen again → clear their miss counters (no join event fires
        # because they were never removed from _previous_players).
        for name in current_names:
            self._miss_counts.pop(name, None)
        for name in confirmed_left:
            self._miss_counts.pop(name, None)

        # Effective online set = currently seen + missing-but-not-yet-confirmed
        # (kept with their last known data).
        effective: dict[str, dict] = dict(all_players)
        for name in missing:
            if name not in confirmed_left:
                effective[name] = previous[name]

        # Full list
        player_list = [
            {
                "name": p["name"], "uuid": p["uuid"], "world": p["world"],
                "foreign": p["foreign"], "position": p["position"],
                "rotation": p["rotation"],
                "residence": p.get("residence"),
                "region": p.get("region"),
                "afk": self.is_player_afk(p["name"]),
            }
            for p in effective.values()
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

        for name in confirmed_left:
            logger.info("Player left: {} (confirmed after {} polls)", name, threshold)
            await sio.emit("player_event", {"name": name, "event": "leave"})
            await self._notify_tracked(name, "leave")
            await self._notify_bot_player(name, "leave")

        # ── AFK detection ───────────────────────────────────────────
        self._update_afk_status(all_players, confirmed_left)

        self._previous_players = effective

    # ── AFK detection ──────────────────────────────────────────────

    def _update_afk_status(
        self,
        current_players: dict[str, dict],
        confirmed_left: list[str] | None = None,
    ) -> None:
        """Compare player positions against last poll to detect AFK."""
        now = time.time()
        for name, p in current_players.items():
            pos = p.get("position") or {}
            x = pos.get("x", 0)
            y = pos.get("y", 0)
            z = pos.get("z", 0)

            prev = self._player_afk_status.get(name)
            if prev is None:
                # Newly seen player — initialize tracking
                self._player_afk_status[name] = {
                    "x": x, "y": y, "z": z,
                    "last_moved_at": now,
                    "afk": False,
                }
                continue

            # Check if position changed (compare all three axes)
            if (abs(x - prev["x"]) > 0.5 or
                abs(y - prev["y"]) > 0.5 or
                abs(z - prev["z"]) > 0.5):
                # Player moved — reset timer
                prev["x"] = x
                prev["y"] = y
                prev["z"] = z
                prev["last_moved_at"] = now
                prev["afk"] = False
            elif now - prev["last_moved_at"] >= self.AFK_THRESHOLD_SECONDS:
                # Stationary for 10+ minutes — mark AFK
                prev["afk"] = True

        # Clean up only players whose leave has been CONFIRMED — a player
        # temporarily missing from a glitchy poll keeps their AFK tracking.
        for name in confirmed_left or []:
            self._player_afk_status.pop(name, None)

    def is_player_afk(self, name: str) -> bool:
        """Check if a player is currently AFK."""
        status = self._player_afk_status.get(name)
        return status["afk"] if status else False

    def get_player_afk_info(self, name: str) -> dict | None:
        """Get full AFK tracking info for a player."""
        return self._player_afk_status.get(name)

    def get_afk_players(self) -> dict[str, bool]:
        """Return {name: afk} for all currently tracked players."""
        return {name: s["afk"] for name, s in self._player_afk_status.items()}

    # ── markers poll (slow, 60s) ────────────────────────────────────

    async def _markers_poll_loop(self) -> None:
        # Poll immediately on startup (so stale DB cache — possibly overworld-only —
        # is replaced with all-world data right away), then every 30s.
        INTERVAL = 30
        while self._running:
            try:
                await self._discover_worlds_once()
                await self._poll_markers_once()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.warning("BlueMap markers poll error: {}", exc)
            await asyncio.sleep(INTERVAL)

    async def _discover_worlds_once(self) -> None:
        """Refresh the configured world list from BlueMap /settings.json.

        BlueMap 5.16 exposes the authoritative world list in the global
        settings endpoint. If the server adds/removes worlds, the monitor
        picks it up automatically instead of being hardcoded.
        """
        try:
            cfg = get_config().bluemap
            url = f"{cfg.api_base_url}/settings.json"
            async with httpx.AsyncClient(timeout=httpx.Timeout(10.0)) as client:
                resp = await client.get(url)
                if resp.status_code != 200:
                    return
                data = resp.json()
            discovered = data.get("maps", [])
            if not isinstance(discovered, list) or not discovered:
                return
            # Preserve configured order for known worlds, then append new ones
            known = ["world", "world_nether", "world_the_end"]
            merged: list[str] = []
            for w in known:
                if w in discovered and w not in merged:
                    merged.append(w)
            for w in discovered:
                if w not in merged:
                    merged.append(w)
            if merged != list(cfg.worlds):
                old = list(cfg.worlds)
                cfg.worlds = merged
                logger.info(
                    "BlueMap world list updated: {} -> {}",
                    old, merged,
                )
        except Exception as exc:
            logger.debug("BlueMap world discovery failed (keeps configured list): {}", exc)

    async def _poll_markers_once(self) -> None:
        cfg = get_config().bluemap

        # Fetch markers for EVERY world — regions/residences live on all maps
        # (world / world_nether / world_the_end), not just the overworld.
        residences: list[dict] = []
        regions: list[dict] = []
        markers: list[dict] = []
        landmarks: list[dict] = []
        metro_lines: list[dict] = []
        metro_stations: list[dict] = []
        per_world_counts: dict[str, tuple[int, int, int, int, int, int]] = {}

        async with httpx.AsyncClient(timeout=httpx.Timeout(15.0)) as client:
            for world in cfg.worlds:
                try:
                    url = f"{cfg.api_base_url}/maps/{world}/live/markers.json"
                    resp = await client.get(url)
                    if resp.status_code != 200:
                        logger.warning("BlueMap markers poll: {} -> HTTP {}", url, resp.status_code)
                        continue
                    data = resp.json()
                except Exception as exc:
                    logger.warning("BlueMap markers poll failed for {}: {}", world, exc)
                    continue

                (w_res, w_reg, w_mk,
                 w_lm, w_ml, w_ms) = self._parse_markers_data(data, world)
                residences.extend(w_res)
                regions.extend(w_reg)
                markers.extend(w_mk)
                landmarks.extend(w_lm)
                metro_lines.extend(w_ml)
                metro_stations.extend(w_ms)
                per_world_counts[world] = (len(w_res), len(w_reg), len(w_mk), len(w_lm), len(w_ml), len(w_ms))

        self._residences = residences
        self._regions = regions
        self._markers = markers
        self._landmarks = landmarks
        self._metro_lines = metro_lines
        self._metro_stations = metro_stations
        logger.info(
            "BlueMap markers refreshed: {} residences, {} regions, {} markers, "
            "{} landmarks, {} metro lines, {} metro stations (per world: {})",
            len(residences), len(regions), len(markers),
            len(landmarks), len(metro_lines), len(metro_stations),
            {w: f"res={c[0]} reg={c[1]} mk={c[2]} lm={c[3]} ml={c[4]} ms={c[5]}" for w, c in per_world_counts.items()},
        )

        # Save to DB for persistence across restarts
        self._save_cache_to_db()

        # Push to clients
        await sio.emit("regions_update", {"regions": regions, "timestamp": time.time()})
        await sio.emit("residences_update", {"residences": residences, "timestamp": time.time()})
        await sio.emit("markers_update", {"markers": markers, "timestamp": time.time()})
        await sio.emit("landmarks_update", {"landmarks": landmarks, "timestamp": time.time()})
        await sio.emit("metro_lines_update", {"metro_lines": metro_lines, "timestamp": time.time()})
        await sio.emit("metro_stations_update", {"metro_stations": metro_stations, "timestamp": time.time()})

    def _parse_markers_data(
        self,
        data: dict,
        world: str,
    ) -> tuple[list[dict], list[dict], list[dict], list[dict], list[dict], list[dict]]:
        """Parse one world's markers.json into 6 marker-set lists.

        Every entry is tagged with its ``world`` id so leaderboards and
        point-in-polygon lookups can distinguish same-named regions across maps.
        Returns (residences, regions, markers, landmarks, metro_lines, metro_stations).
        """
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
                "world": world,
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
                "world": world,
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
                "world": world,
                "label": mk.get("label", key),
                "position": mk.get("position"),
                "type": mk.get("type", ""),
                "detail": _strip_html(mk.get("detail", ""))[:200],
            })

        # Parse server landmarks (mangopassport-landmarks) — 地标含类型分类
        landmarks: list[dict] = []
        lm_group = data.get("mangopassport-landmarks", {}).get("markers", {})
        for key, mk in lm_group.items():
            detail_html = mk.get("detail", "")
            detail_text = _strip_html(detail_html)
            # 类型字段: "类型：停车场<br>..." — match on raw HTML so <br>
            # acts as a terminator (strip_html removes <br> without newline).
            lm_type = ""
            m_type = re.search(r"类型\s*[:：]\s*([^<，,]+?)(?=<br|坐标|$)", detail_html)
            if m_type:
                lm_type = m_type.group(1).strip()
            landmarks.append({
                "id": key,
                "world": world,
                "label": mk.get("label", key),
                "position": mk.get("position"),
                "type": lm_type,
                "detail": detail_text[:200],
            })

        # Parse metro lines (folia-metro-lines) — 地铁线路（含 line 几何数据）
        metro_lines: list[dict] = []
        ml_group = data.get("folia-metro-lines", {}).get("markers", {})
        for key, mk in ml_group.items():
            metro_lines.append({
                "id": key,
                "world": world,
                "label": mk.get("label", key),
                "line": mk.get("line", []),
                "line_color": _rgba_to_css(mk.get("lineColor")),
                "detail": _strip_html(mk.get("detail", ""))[:200],
                "position": mk.get("position"),
            })

        # Parse metro stations (folia-metro-stations) — 地铁站点
        metro_stations: list[dict] = []
        ms_group = data.get("folia-metro-stations", {}).get("markers", {})
        for key, mk in ms_group.items():
            metro_stations.append({
                "id": key,
                "world": world,
                "label": mk.get("label", key),
                "position": mk.get("position"),
                "type": mk.get("type", ""),
                "detail": _strip_html(mk.get("detail", ""))[:200],
            })

        return residences, regions, markers, landmarks, metro_lines, metro_stations

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
                from sqlalchemy import text
                for key, data in [
                    ("bluemap_residences", self._residences),
                    ("bluemap_regions", self._regions),
                    ("bluemap_markers", self._markers),
                    ("bluemap_landmarks", self._landmarks),
                    ("bluemap_metro_lines", self._metro_lines),
                    ("bluemap_metro_stations", self._metro_stations),
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
                    # Legacy cache (pre multi-world markers) has no `world` tag —
                    # it was fetched from the overworld only, so tag as `world`.
                    for item in data:
                        if isinstance(item, dict) and "world" not in item:
                            item["world"] = "world"
                    if key == "bluemap_residences":
                        self._residences = data
                    elif key == "bluemap_regions":
                        self._regions = data
                    elif key == "bluemap_markers":
                        self._markers = data
                    elif key == "bluemap_landmarks":
                        self._landmarks = data
                    elif key == "bluemap_metro_lines":
                        self._metro_lines = data
                    elif key == "bluemap_metro_stations":
                        self._metro_stations = data
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

    def _find_residence(self, x: float, y: float, z: float, world: Optional[str] = None) -> Optional[dict]:
        for r in self._residences:
            if world and r.get("world") and r["world"] != world:
                continue
            if y < r["min_y"] or y > r["max_y"]:
                continue
            if _point_in_polygon_2d(x, z, r["shape"]):
                return {"name": r["label"], "owner": r["owner"], "area": r["area"]}
        return None

    def _find_region(self, x: float, z: float, world: Optional[str] = None) -> Optional[dict]:
        for r in self._regions:
            if world and r.get("world") and r["world"] != world:
                continue
            if _point_in_polygon_2d(x, z, r["shape"]):
                return {
                    "label": r["label"], "tps": r["tps"], "mspt": r["mspt"],
                    "entities": r["entities"], "players_in_region": r["players_in_region"],
                    "chunks": r["chunks"], "sections": r["sections"],
                    "world": r.get("world"),
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

    def get_landmarks(self) -> list[dict]:
        return self._landmarks

    def get_metro_lines(self) -> list[dict]:
        return self._metro_lines

    def get_metro_stations(self) -> list[dict]:
        return self._metro_stations

    def get_worlds(self) -> list[str]:
        """Return the list of worlds the monitor polls (config or discovered)."""
        cfg = get_config().bluemap
        return list(cfg.worlds)


# ── helpers ────────────────────────────────────────────────────────

def _extract_float(text: str, pattern: str) -> Optional[float]:
    m = re.search(pattern, text)
    return float(m.group(1)) if m else None


def _extract_int(text: str, pattern: str) -> Optional[int]:
    m = re.search(pattern, text)
    return int(m.group(1)) if m else None


def _strip_html(text: str) -> str:
    return re.sub(r"<[^>]+>", "", text).strip()


def _rgba_to_css(color) -> Optional[str]:
    """Convert BlueMap lineColor (dict {r,g,b,a} or hex string) to CSS color."""
    if color is None:
        return None
    if isinstance(color, str):
        return color if color.startswith("#") else f"#{color}"
    if isinstance(color, dict):
        r = int(color.get("r", 0) * 255) if isinstance(color.get("r"), float) else int(color.get("r", 0))
        g = int(color.get("g", 0) * 255) if isinstance(color.get("g"), float) else int(color.get("g", 0))
        b = int(color.get("b", 0) * 255) if isinstance(color.get("b"), float) else int(color.get("b", 0))
        a = color.get("a")
        if a is not None and a < 1.0:
            return f"rgba({r},{g},{b},{a})"
        return f"rgb({r},{g},{b})"
    return None
