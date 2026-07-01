"""Monitoring API routes."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from typing import Optional

from vmtools_next.api.deps import get_current_user

router = APIRouter(prefix="/api/monitor", tags=["monitor"])


class MetricResponse(BaseModel):
    timestamp: float
    cpu_percent: float
    memory_percent: float
    memory_used: int = 0
    memory_total: int = 0
    disk_percent: float
    disk_used: int = 0
    disk_total: int = 0
    net_bytes_sent: int = 0
    net_bytes_recv: int = 0


@router.get("/metrics", response_model=list[MetricResponse])
def get_metrics(count: int = 100, user=Depends(get_current_user)):
    """Get recent system metrics."""
    try:
        from vmtools_next.main import get_monitor
        monitor = get_monitor()
        if monitor:
            raw = monitor.get_metrics(count)
            return [
                MetricResponse(
                    timestamp=m.get("timestamp", 0),
                    cpu_percent=m.get("cpu_percent", 0),
                    memory_percent=m.get("memory_percent", 0),
                    memory_used=m.get("memory_used", 0),
                    memory_total=m.get("memory_total", 0),
                    disk_percent=m.get("disk_percent", 0),
                    disk_used=m.get("disk_used", 0),
                    disk_total=m.get("disk_total", 0),
                    net_bytes_sent=m.get("net_bytes_sent", 0),
                    net_bytes_recv=m.get("net_bytes_recv", 0),
                )
                for m in raw
            ]
    except Exception:
        pass
    return []


@router.get("/alerts")
def get_alerts(user=Depends(get_current_user)):
    """Get recent alerts."""
    try:
        from vmtools_next.main import get_alert_engine
        engine = get_alert_engine()
        if engine:
            # Return rules as alert summary
            return [
                {
                    "name": r.name,
                    "metric_name": r.metric_name,
                    "operator": r.operator,
                    "threshold": r.threshold,
                    "severity": r.severity,
                    "enabled": r.enabled,
                }
                for r in engine._rules
            ]
    except Exception:
        pass
    return []


@router.get("/health")
def monitor_health():
    """Public health check (no auth required)."""
    return {"status": "ok", "service": "vmtools-next"}


@router.get("/bots/summary")
def bots_summary(user=Depends(get_current_user)):
    """Bot summary for dashboard."""
    try:
        from vmtools_next.data.db import get_session_factory
        from vmtools_next.data.models.logistics import MccBotModel
        Session = get_session_factory()
        db = Session()
        try:
            bots = db.query(MccBotModel).all()
            online = sum(1 for b in bots if b.status == "online")
            return {
                "total": len(bots),
                "online": online,
                "offline": len(bots) - online,
            }
        finally:
            db.close()
    except Exception:
        return {"total": 0, "online": 0, "offline": 0}
