"""BlueMap data API — serve cached markers, residences, and region performance."""
from __future__ import annotations

from fastapi import APIRouter

from vmtools_next.data.models.auth import UserModel
from vmtools_next.api.deps import get_current_user

router = APIRouter(prefix="/api/bluemap", tags=["bluemap"])


def _get_monitor():
    from vmtools_next.main import get_bluemap_monitor
    return get_bluemap_monitor()


@router.get("/regions")
def get_regions(user: UserModel = get_current_user):
    """Return all Folia regions with TPS/MSPT/entity performance data."""
    monitor = _get_monitor()
    regions = monitor.get_regions() if monitor else []
    return {"regions": regions, "count": len(regions)}


@router.get("/residences")
def get_residences(user: UserModel = get_current_user):
    """Return all player residences with owner, area, and polygon shape."""
    monitor = _get_monitor()
    residences = monitor.get_residences() if monitor else []
    # Sort by area descending for rankings
    sorted_res = sorted(residences, key=lambda r: r.get("area", 0), reverse=True)
    return {"residences": sorted_res, "count": len(sorted_res)}


@router.get("/markers")
def get_markers(user: UserModel = get_current_user):
    """Return all custom map markers."""
    monitor = _get_monitor()
    markers = monitor.get_markers() if monitor else []
    return {"markers": markers, "count": len(markers)}
