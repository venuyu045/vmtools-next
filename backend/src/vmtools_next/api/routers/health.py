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


@router.get("/ping")
def ping():
    """轻量延迟探测（无 DB 访问，用于前端 RTT 指示器）。"""
    return {"ok": True, "server_time_ms": int(time.time() * 1000)}


@router.get("/health")
def health_check(db: Session = Depends(get_db)):
    """Health check: service status + DB ping + uptime.

    ⚠️ 2026-10-20 审查修复（中等·信息泄露）：
      本接口**无需认证**（nginx/容器 healthcheck 与公网探活都用它）。
      原实现把数据库异常原文直接拼进响应体（``f"error: {e}"``），
      SQLAlchemy 的 OperationalError 消息里通常包含**数据库绝对路径**
      （如 ``unable to open database file: /opt/vmtools-next/data/vmtools-next.db``）
      以及 SQL 片段 —— 未登录访客即可读到服务器目录结构。
      修复：响应体只给 ``"error"`` 这一状态词，异常详情写入服务端日志。
    """
    checks = {"service": "ok"}

    # Database ping
    try:
        db.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception as e:
        logger.warning("Health check DB ping failed: {}", e)
        checks["database"] = "error"

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
