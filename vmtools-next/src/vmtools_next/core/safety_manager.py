"""Safety Manager — rate limiting and circuit breaking for automation operations.

Ported from VMTools-v3 SafetyManager.java. Provides:
  - Rate limiting: isOperationAllowed() checks if enough time has passed
  - Circuit breaking: stops after max_failures consecutive failures
  - Nearby player detection: pauses when players are too close
"""
from __future__ import annotations

import time
import logging
from typing import Optional

from vmtools_next.core.dataclasses import CheckResult, AutomationSafetyPolicy

logger = logging.getLogger("vmtools.safety")


class SafetyManager:
    """Rate limiter and circuit breaker for automation operations."""

    def __init__(self, policy: Optional[AutomationSafetyPolicy] = None):
        self._policy = policy or AutomationSafetyPolicy()
        self._last_operation_time: dict[str, float] = {}
        self._failure_count: int = 0
        self._emergency_stop: bool = False
        self._paused_by_player: bool = False

    @property
    def policy(self) -> AutomationSafetyPolicy:
        return self._policy

    @policy.setter
    def policy(self, value: AutomationSafetyPolicy) -> None:
        self._policy = value

    def reset_failures(self) -> None:
        """Reset the failure counter (call after a successful operation)."""
        self._failure_count = 0

    def record_failure(self) -> None:
        """Record a failure. Triggers emergency stop if threshold exceeded."""
        self._failure_count += 1
        if self._failure_count >= self._policy.max_failures_before_stop:
            self._emergency_stop = True
            logger.error("EMERGENCY STOP: %d consecutive failures (threshold: %d)",
                         self._failure_count, self._policy.max_failures_before_stop)

    def is_emergency_stopped(self) -> bool:
        return self._emergency_stop

    def clear_emergency_stop(self) -> None:
        self._emergency_stop = False
        self._failure_count = 0
        logger.info("Emergency stop cleared")

    def is_operation_allowed(self, operation_type: str = "default") -> bool:
        """Check if enough time has passed since the last operation of this type."""
        now = time.monotonic()
        last = self._last_operation_time.get(operation_type, 0)
        interval = self._get_interval(operation_type)
        if now - last < interval:
            return False
        self._last_operation_time[operation_type] = now
        return True

    def _get_interval(self, operation_type: str) -> float:
        """Get the minimum interval (seconds) for an operation type."""
        intervals = {
            "place": self._policy.place_interval_ticks * 0.05,  # tick → seconds
            "container": self._policy.container_interact_interval * 0.05,
            "teleport": self._policy.teleport_cooldown_seconds,
            "default": self._policy.max_ops_per_tick * 0.05,
        }
        return intervals.get(operation_type, intervals["default"])

    async def check(self, nearby_player_detected: bool = False) -> CheckResult:
        """Perform a safety check. Returns CheckResult enum.

        Args:
            nearby_player_detected: True if a player is within nearby_player_radius.
        """
        if self._emergency_stop:
            return CheckResult.EMERGENCY_STOP

        if self._policy.pause_on_nearby_player and nearby_player_detected:
            if not self._paused_by_player:
                self._paused_by_player = True
                logger.info("Paused: nearby player detected (radius=%d)",
                            self._policy.nearby_player_radius)
            return CheckResult.BLOCKED

        if self._paused_by_player and not nearby_player_detected:
            self._paused_by_player = False
            logger.info("Resumed: nearby player left")

        return CheckResult.OK
