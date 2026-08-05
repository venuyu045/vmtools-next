"""BlueMap data API — serve cached markers, residences, and region performance."""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends

from vmtools_next.api.deps import get_current_user

router = APIRouter(prefix="/api/bluemap", tags=["bluemap"])


def _get_monitor():
    from vmtools_next.main import get_bluemap_monitor
    return get_bluemap_monitor()


def _load_from_db_cache(key: str) -> list[dict]:
    """Fallback: load cached data from bluemap_cache table."""
    try:
        from vmtools_next.data.db import get_session_factory
        from sqlalchemy import text
        Session = get_session_factory()
        db = Session()
        try:
            row = db.execute(
                text("SELECT cache_data FROM bluemap_cache WHERE cache_key = :key"),
                {"key": key},
            ).fetchone()
            if row and row[0]:
                return json.loads(row[0])
        finally:
            db.close()
    except Exception:
        pass
    return []


@router.get("/regions")
def get_regions(user=Depends(get_current_user)):
    monitor = _get_monitor()
    regions = monitor.get_regions() if monitor else []
    if not regions:
        regions = _load_from_db_cache("bluemap_regions")
    return {"regions": regions, "count": len(regions)}


@router.get("/residences")
def get_residences(user=Depends(get_current_user)):
    monitor = _get_monitor()
    residences = monitor.get_residences() if monitor else []
    if not residences:
        residences = _load_from_db_cache("bluemap_residences")
    sorted_res = sorted(residences, key=lambda r: r.get("area", 0), reverse=True)
    return {"residences": sorted_res, "count": len(sorted_res)}


@router.get("/markers")
def get_markers(user=Depends(get_current_user)):
    monitor = _get_monitor()
    markers = monitor.get_markers() if monitor else []
    if not markers:
        markers = _load_from_db_cache("bluemap_markers")
    return {"markers": markers, "count": len(markers)}


@router.get("/landmarks")
def get_landmarks(user=Depends(get_current_user)):
    """服务器地标（mangopassport-landmarks，含类型分类）。"""
    monitor = _get_monitor()
    landmarks = monitor.get_landmarks() if monitor else []
    if not landmarks:
        landmarks = _load_from_db_cache("bluemap_landmarks")
    return {"landmarks": landmarks, "count": len(landmarks)}


@router.get("/metro-lines")
def get_metro_lines(user=Depends(get_current_user)):
    """地铁线路（folia-metro-lines，含线几何数据）。"""
    monitor = _get_monitor()
    lines = monitor.get_metro_lines() if monitor else []
    if not lines:
        lines = _load_from_db_cache("bluemap_metro_lines")
    return {"metro_lines": lines, "count": len(lines)}


@router.get("/metro-stations")
def get_metro_stations(user=Depends(get_current_user)):
    """地铁站点（folia-metro-stations）。"""
    monitor = _get_monitor()
    stations = monitor.get_metro_stations() if monitor else []
    if not stations:
        stations = _load_from_db_cache("bluemap_metro_stations")
    return {"metro_stations": stations, "count": len(stations)}


@router.get("/worlds")
def get_worlds(user=Depends(get_current_user)):
    """当前监控的世界列表（可动态发现）。"""
    monitor = _get_monitor()
    worlds = monitor.get_worlds() if monitor else []
    return {"worlds": worlds, "count": len(worlds)}


@router.post("/refresh")
async def refresh_markers(user=Depends(get_current_user)):
    """Manually trigger a markers poll and return updated data."""
    monitor = _get_monitor()
    if not monitor:
        return {"ok": False, "message": "monitor not running"}

    try:
        await monitor._discover_worlds_once()
        await monitor._poll_markers_once()
    except Exception as exc:
        return {"ok": False, "message": str(exc) or repr(exc)}

    residences = monitor.get_residences()
    regions = monitor.get_regions()
    markers = monitor.get_markers()
    landmarks = monitor.get_landmarks()
    metro_lines = monitor.get_metro_lines()
    metro_stations = monitor.get_metro_stations()

    from vmtools_next.data.db import sio
    try:
        await sio.emit("regions_update", {"regions": regions})
        await sio.emit("residences_update", {"residences": residences})
        await sio.emit("markers_update", {"markers": markers})
        await sio.emit("landmarks_update", {"landmarks": landmarks})
        await sio.emit("metro_lines_update", {"metro_lines": metro_lines})
        await sio.emit("metro_stations_update", {"metro_stations": metro_stations})
    except Exception:
        pass

    return {
        "ok": True,
        "residences": len(residences),
        "regions": len(regions),
        "markers": len(markers),
        "landmarks": len(landmarks),
        "metro_lines": len(metro_lines),
        "metro_stations": len(metro_stations),
    }
