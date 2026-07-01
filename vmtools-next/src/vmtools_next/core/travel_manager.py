"""Travel Manager — decides between pathfinding and teleportation.

Ported from VMTools-v3 TravelManager.java. Uses distance threshold to
decide whether to use Baritone pathfinding or teleport commands.
"""
from __future__ import annotations

import logging
from typing import Optional

from vmtools_next.core.dataclasses import TravelTarget, TeleportCommandTemplate

logger = logging.getLogger("vmtools.travel")


class TravelManager:
    """Decides travel mode and coordinates travel operations."""

    def __init__(self, teleport_threshold: int = 200,
                 arrival_verify_radius: int = 3,
                 arrival_timeout_seconds: int = 10,
                 max_teleports_per_minute: int = 6):
        self._teleport_threshold = teleport_threshold
        self._arrival_verify_radius = arrival_verify_radius
        self._arrival_timeout = arrival_timeout_seconds
        self._max_teleports_per_minute = max_teleports_per_minute
        self._teleport_count: int = 0
        self._teleport_window_start: float = 0
        self._current_target: Optional[TravelTarget] = None

    @property
    def current_target(self) -> Optional[TravelTarget]:
        return self._current_target

    def should_teleport(self, distance: float) -> bool:
        """Decide whether to teleport based on distance."""
        return distance >= self._teleport_threshold

    def can_teleport(self) -> bool:
        """Check if we haven't exceeded the teleport rate limit."""
        import time
        now = time.monotonic()
        if now - self._teleport_window_start > 60:
            self._teleport_count = 0
            self._teleport_window_start = now
        return self._teleport_count < self._max_teleports_per_minute

    def record_teleport(self) -> None:
        self._teleport_count += 1

    def get_arrival_radius(self) -> int:
        return self._arrival_verify_radius

    def get_arrival_timeout(self) -> int:
        return self._arrival_timeout


class TeleportManager:
    """Manages teleport command templates and cooldowns."""

    def __init__(self, templates: Optional[list[TeleportCommandTemplate]] = None):
        self._templates = templates or [TeleportCommandTemplate()]
        self._last_teleport_time: float = 0
        self._active_template_index: int = 0

    def get_command(self, player: str, x: int, y: int, z: int) -> str:
        """Generate a teleport command using the active template."""
        template = self._templates[self._active_template_index]
        return template.format(player, x, y, z)

    def is_on_cooldown(self) -> bool:
        """Check if teleport is on cooldown."""
        import time
        template = self._templates[self._active_template_index]
        return (time.monotonic() - self._last_teleport_time) < template.cooldown_seconds

    def record_use(self) -> None:
        """Record a teleport use (starts cooldown)."""
        import time
        self._last_teleport_time = time.monotonic()

    def cycle_template(self) -> None:
        """Switch to the next template (for fallback)."""
        if len(self._templates) > 1:
            self._active_template_index = (self._active_template_index + 1) % len(self._templates)
