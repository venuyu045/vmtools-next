"""Operation Logger — records automation operations to database.

Ported from VMTools-v3 OperationLogger.java. Logs operations with type,
details, success status, and duration for debugging and monitoring.
"""
from __future__ import annotations

import time
import logging
from typing import Optional, Callable

from vmtools_next.core.dataclasses import OperationLogEntry, OperationType

logger = logging.getLogger("vmtools.operation_logger")


class OperationLogger:
    """Logs automation operations for debugging and monitoring.

    Optionally persists to database when db_session_factory is provided.
    """

    def __init__(self, db_session_factory: Optional[Callable] = None):
        self._entries: list[OperationLogEntry] = []
        self._max_entries = 10000  # Keep last N entries in memory
        self._db_factory = db_session_factory

    def log(self, operation_type: OperationType, bot_id: str = "",
            warehouse_id: str = "", details: str = "",
            success: bool = True, duration_ms: int = 0) -> None:
        """Log an operation."""
        entry = OperationLogEntry(
            operation_type=operation_type,
            bot_id=bot_id,
            warehouse_id=warehouse_id,
            details=details,
            success=success,
            duration_ms=duration_ms,
            timestamp=time.time(),
        )
        self._entries.append(entry)

        # Trim if too many entries
        if len(self._entries) > self._max_entries:
            self._entries = self._entries[-self._max_entries:]

        level = logging.INFO if success else logging.WARNING
        logger.log(level, "[%s] bot=%s warehouse=%s %s (duration=%dms)",
                   operation_type.value, bot_id, warehouse_id, details, duration_ms)

        # Persist to database if factory is available
        if self._db_factory:
            self._persist_to_db(entry)

    def _persist_to_db(self, entry: OperationLogEntry) -> None:
        """Persist a log entry to the database."""
        try:
            from vmtools_next.data.models.logistics import OperationLogModel
            db = self._db_factory()
            db.add(OperationLogModel(
                operation_type=entry.operation_type.value,
                bot_id=entry.bot_id,
                warehouse_id=entry.warehouse_id,
                details=entry.details,
                success=entry.success,
                duration_ms=entry.duration_ms,
            ))
            db.commit()
            db.close()
        except Exception as e:
            # Don't let DB errors break the logger
            logger.debug("Failed to persist operation log to DB: %s", e)

    def get_recent(self, count: int = 100,
                    operation_type: Optional[OperationType] = None) -> list[OperationLogEntry]:
        """Get recent log entries, optionally filtered by type."""
        entries = self._entries
        if operation_type:
            entries = [e for e in entries if e.operation_type == operation_type]
        return entries[-count:]

    def get_failure_count(self, operation_type: Optional[OperationType] = None,
                          time_window_seconds: float = 300) -> int:
        """Count failures in the last time_window_seconds."""
        cutoff = time.time() - time_window_seconds
        failures = [
            e for e in self._entries
            if not e.success and e.timestamp >= cutoff
            and (operation_type is None or e.operation_type == operation_type)
        ]
        return len(failures)

    def clear(self) -> None:
        self._entries.clear()
