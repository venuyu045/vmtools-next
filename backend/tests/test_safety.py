"""Tests for safety manager."""
import pytest
import time
from vmtools_next.core.safety_manager import SafetyManager
from vmtools_next.core.dataclasses import CheckResult, AutomationSafetyPolicy


class TestSafetyManager:
    def test_initial_state(self):
        sm = SafetyManager()
        assert sm.is_emergency_stopped() == False
        # check() is async, test the sync properties instead
        assert sm._emergency_stop == False

    def test_rate_limiting(self):
        policy = AutomationSafetyPolicy(teleport_cooldown_seconds=1)
        sm = SafetyManager(policy=policy)
        assert sm.is_operation_allowed("teleport") == True
        assert sm.is_operation_allowed("teleport") == False  # Too soon
        time.sleep(1.1)
        assert sm.is_operation_allowed("teleport") == True

    def test_circuit_breaker(self):
        policy = AutomationSafetyPolicy(max_failures_before_stop=3)
        sm = SafetyManager(policy=policy)
        assert sm.is_emergency_stopped() == False
        sm.record_failure()
        sm.record_failure()
        assert sm.is_emergency_stopped() == False
        sm.record_failure()
        assert sm.is_emergency_stopped() == True

    def test_clear_emergency_stop(self):
        sm = SafetyManager()
        sm.record_failure()
        sm.record_failure()
        sm.record_failure()
        assert sm.is_emergency_stopped() == True
        sm.clear_emergency_stop()
        assert sm.is_emergency_stopped() == False

    def test_reset_failures(self):
        sm = SafetyManager()
        sm.record_failure()
        sm.record_failure()
        sm.reset_failures()
        assert sm._failure_count == 0
