"""Alert Engine — evaluates threshold rules and triggers alerts.

Evaluates rules from alert_rules table against collected metrics.
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Optional, Callable, Awaitable

logger = logging.getLogger("vmtools.alerts")

# Alert callback: (rule_name, severity, message, metric_value)
AlertCallback = Callable[[str, str, str, float], Awaitable[None]]


class AlertRule:
    """A threshold-based alert rule."""

    def __init__(self, name: str, metric_name: str, operator: str,
                 threshold: float, severity: str = "warning",
                 cooldown_seconds: int = 300):
        self.name = name
        self.metric_name = metric_name
        self.operator = operator
        self.threshold = threshold
        self.severity = severity
        self.cooldown_seconds = cooldown_seconds
        self.last_triggered: float = 0

    def evaluate(self, value: float) -> bool:
        """Check if the rule is triggered."""
        ops = {
            ">": lambda a, b: a > b,
            "<": lambda a, b: a < b,
            ">=": lambda a, b: a >= b,
            "<=": lambda a, b: a <= b,
            "==": lambda a, b: a == b,
        }
        op = ops.get(self.operator)
        if not op:
            return False
        return op(value, self.threshold)

    def is_on_cooldown(self) -> bool:
        return (time.time() - self.last_triggered) < self.cooldown_seconds


class AlertEngine:
    """Evaluates alert rules against metrics."""

    def __init__(self, check_interval: int = 30):
        self._rules: list[AlertRule] = []
        self._check_interval = check_interval
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._callback: Optional[AlertCallback] = None
        self._metrics_provider: Optional[Callable] = None

    def set_callback(self, callback: AlertCallback) -> None:
        self._callback = callback

    def set_metrics_provider(self, provider: Callable) -> None:
        self._metrics_provider = provider

    def add_rule(self, rule: AlertRule) -> None:
        self._rules.append(rule)
        logger.info("Added alert rule: %s (%s %s %.1f)", rule.name, rule.metric_name, rule.operator, rule.threshold)

    def add_default_rules(self) -> None:
        """Add default system alert rules."""
        self.add_rule(AlertRule("High CPU", "cpu_percent", ">", 80, "warning"))
        self.add_rule(AlertRule("Critical CPU", "cpu_percent", ">", 95, "critical"))
        self.add_rule(AlertRule("High Memory", "memory_percent", ">", 90, "warning"))
        self.add_rule(AlertRule("Critical Memory", "memory_percent", ">", 98, "critical"))
        self.add_rule(AlertRule("Low Disk", "disk_percent", ">", 90, "warning"))

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._check_loop())
        logger.info("Alert engine started (interval=%ds, rules=%d)",
                     self._check_interval, len(self._rules))

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()

    async def _check_loop(self) -> None:
        while self._running:
            try:
                if self._metrics_provider:
                    metrics = self._metrics_provider()
                    if metrics:
                        await self._evaluate_rules(metrics)
            except Exception as e:
                logger.warning("Alert check error: %s", e)
            await asyncio.sleep(self._check_interval)

    async def _evaluate_rules(self, metrics: dict) -> None:
        for rule in self._rules:
            value = metrics.get(rule.metric_name)
            if value is None:
                continue
            if rule.evaluate(value) and not rule.is_on_cooldown():
                rule.last_triggered = time.time()
                message = f"{rule.name}: {rule.metric_name}={value:.1f} {rule.operator} {rule.threshold}"
                logger.warning("ALERT [%s]: %s", rule.severity, message)
                if self._callback:
                    try:
                        await self._callback(rule.name, rule.severity, message, value)
                    except Exception as e:
                        logger.warning("Alert callback error: %s", e)
