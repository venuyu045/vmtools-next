"""Health check endpoint.

GET /api/health — returns service status, database connectivity, and uptime.
"""
from __future__ import annotations

import time
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from vmtools_next.api.deps import get_db
from vmtools_next.infra.logging import get_logger

router = APIRouter(prefix="/api", tags=["health"])
logger = get_logger("api.health")

_start_time = time.monotonic()


@router.get("/health")
def health_check(db: Session = Depends(get_db)):
    """Health check: service status + DB ping + uptime."""
    checks = {"service": "ok"}

    # Database ping
    try:
        db.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception as e:
        checks["database"] = f"error: {e}"

    # Uptime
    uptime_seconds = round(time.monotonic() - _start_time, 1)
    checks["uptime_seconds"] = uptime_seconds

    # MCC status (will be populated by MccSessionPool in later phases)
    checks["mcc"] = "not_configured"

    overall = "ok" if checks.get("database") == "ok" else "degraded"
    return {
        "status": overall,
        "service": "vmtools-next",
        "version": "0.1.0",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        **checks,
    }
