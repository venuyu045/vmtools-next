"""Monitoring API routes."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from vmtools_next.api.deps import require_admin

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
    net_sent_rate: float = 0.0  # bytes/s
    net_recv_rate: float = 0.0  # bytes/s


@router.get("/metrics", response_model=list[MetricResponse])
def get_metrics(count: int = Query(default=100, ge=1, le=500), user=Depends(require_admin)):
    """Get recent system metrics (admin only, count capped at 500)."""
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
                    net_sent_rate=m.get("net_sent_rate", 0.0),
                    net_recv_rate=m.get("net_recv_rate", 0.0),
                )
                for m in raw
            ]
    except Exception:
        pass
    return []


@router.get("/alerts")
def get_alerts(user=Depends(require_admin)):
    """Get alert rules (admin only)."""
    try:
        from vmtools_next.main import get_alert_engine
        engine = get_alert_engine()
        if engine:
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


@router.get("/alerts/events")
def get_alert_events(count: int = Query(default=100, ge=1, le=200), user=Depends(require_admin)):
    """Get recent alert events (触发历史时间线，admin only)."""
    try:
        from vmtools_next.main import get_alert_engine
        engine = get_alert_engine()
        if engine:
            return engine.get_events(count)
    except Exception:
        pass
    return []


@router.get("/processes")
def get_processes(user=Depends(require_admin)):
    """Get latest bot/server process resource snapshot (admin only)."""
    try:
        from vmtools_next.main import get_monitor
        monitor = get_monitor()
        if monitor:
            return monitor.get_processes()
    except Exception:
        pass
    return []


@router.get("/health")
def monitor_health():
    """Public health check (no auth required)."""
    return {"status": "ok", "service": "vmtools-next"}


@router.get("/bots/summary")
def bots_summary(user=Depends(require_admin)):
    """Bot summary (admin only)."""
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