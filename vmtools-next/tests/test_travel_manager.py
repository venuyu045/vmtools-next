"""Tests for TravelManager and TeleportManager."""
import time
import pytest

from vmtools_next.core.travel_manager import TravelManager, TeleportManager
from vmtools_next.core.dataclasses import TeleportCommandTemplate


class TestTravelManager:
    """Test TravelManager."""

    def test_should_teleport_short_distance(self):
        """Test that short distance should not teleport."""
        manager = TravelManager(teleport_threshold=200)
        assert manager.should_teleport(100) is False

    def test_should_teleport_long_distance(self):
        """Test that long distance should teleport."""
        manager = TravelManager(teleport_threshold=200)
        assert manager.should_teleport(300) is True

    def test_should_teleport_exact_threshold(self):
        """Test distance exactly at threshold."""
        manager = TravelManager(teleport_threshold=200)
        assert manager.should_teleport(200) is True

    def test_can_teleport_within_limit(self):
        """Test teleport within rate limit."""
        manager = TravelManager(max_teleports_per_minute=3)
        # Need to call can_teleport() first to initialize the window
        assert manager.can_teleport() is True
        manager.record_teleport()
        assert manager.can_teleport() is True

    def test_can_teleport_exceeds_limit(self):
        """Test teleport exceeding rate limit."""
        manager = TravelManager(max_teleports_per_minute=2)
        # Initialize the window by calling can_teleport() first
        manager.can_teleport()
        manager.record_teleport()
        manager.record_teleport()
        assert manager.can_teleport() is False

    def test_teleport_rate_limit_resets(self):
        """Test that rate limit resets after time window."""
        manager = TravelManager(max_teleports_per_minute=1)
        # Initialize the window
        manager.can_teleport()
        manager.record_teleport()
        assert manager.can_teleport() is False

        # Manually reset the window by setting it to the past
        manager._teleport_window_start = time.monotonic() - 61
        assert manager.can_teleport() is True

    def test_arrival_radius(self):
        """Test getting arrival radius."""
        manager = TravelManager(arrival_verify_radius=5)
        assert manager.get_arrival_radius() == 5

    def test_arrival_timeout(self):
        """Test getting arrival timeout."""
        manager = TravelManager(arrival_timeout_seconds=15)
        assert manager.get_arrival_timeout() == 15


class TestTeleportManager:
    """Test TeleportManager."""

    def test_get_command_default(self):
        """Test getting teleport command with default template."""
        manager = TeleportManager()
        cmd = manager.get_command("Steve", 100, 64, 200)
        assert cmd == "/tp Steve 100 64 200"

    def test_get_command_custom_template(self):
        """Test getting teleport command with custom template."""
        template = TeleportCommandTemplate(
            template="/tpa {player} {x} {y} {z}",
            cooldown_seconds=10.0,
        )
        manager = TeleportManager([template])
        cmd = manager.get_command("Steve", 100, 64, 200)
        assert cmd == "/tpa Steve 100 64 200"

    def test_cooldown_initial(self):
        """Test initial cooldown state."""
        manager = TeleportManager()
        assert manager.is_on_cooldown() is False

    def test_cooldown_after_use(self):
        """Test cooldown after teleport use."""
        template = TeleportCommandTemplate(cooldown_seconds=5.0)
        manager = TeleportManager([template])
        manager.record_use()
        assert manager.is_on_cooldown() is True

    def test_cooldown_expired(self):
        """Test cooldown after it expires."""
        template = TeleportCommandTemplate(cooldown_seconds=0.1)
        manager = TeleportManager([template])
        manager.record_use()
        time.sleep(0.15)
        assert manager.is_on_cooldown() is False

    def test_cycle_template(self):
        """Test cycling between templates."""
        templates = [
            TeleportCommandTemplate(template="/tp {player} {x} {y} {z}"),
            TeleportCommandTemplate(template="/tpa {player} {x} {y} {z}"),
        ]
        manager = TeleportManager(templates)

        cmd1 = manager.get_command("Steve", 100, 64, 200)
        assert cmd1 == "/tp Steve 100 64 200"

        manager.cycle_template()
        cmd2 = manager.get_command("Steve", 100, 64, 200)
        assert cmd2 == "/tpa Steve 100 64 200"

        manager.cycle_template()
        cmd3 = manager.get_command("Steve", 100, 64, 200)
        assert cmd3 == "/tp Steve 100 64 200"  # Back to first

    def test_cycle_single_template(self):
        """Test cycling with single template (should stay on same)."""
        manager = TeleportManager()
        manager.cycle_template()
        cmd = manager.get_command("Steve", 100, 64, 200)
        assert cmd == "/tp Steve 100 64 200"
