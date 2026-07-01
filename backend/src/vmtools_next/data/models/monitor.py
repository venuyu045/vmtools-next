"""Monitoring & alerting ORM models (NEW).

Tables: alert_rules, alert_history, metrics_snapshot

The infra/monitor.py module writes system metrics (CPU/mem/disk/net) every
10s into metrics_snapshot. The infra/alerts.py module evaluates alert_rules
every 30s and records triggers in alert_history.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Column, String, Integer, Float, Boolean, DateTime, Text, ForeignKey, Index
from sqlalchemy.orm import relationship

from vmtools_next.data.db import Base


class AlertRuleModel(Base):
    """A threshold-based alert rule.

    Example: metric_name='cpu', operator='>', threshold=80, severity='warning'
    triggers when CPU > 80%.
    """

    __tablename__ = "alert_rules"

    rule_id = Column(String, primary_key=True)
    name = Column(String, nullable=False)
    metric_name = Column(String, nullable=False)  # cpu|memory|disk|bot_offline|task_failure_rate
    operator = Column(String, nullable=False)  # >|<|>=|<=|==
    threshold = Column(Float, nullable=False)
    severity = Column(String, default="warning", nullable=False)  # info|warning|error|critical
    enabled = Column(Boolean, default=True, nullable=False)
    cooldown_seconds = Column(Integer, default=300, nullable=False)
    webhook_url = Column(String, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

    history = relationship("AlertHistoryModel", back_populates="rule", cascade="all, delete-orphan")


class AlertHistoryModel(Base):
    """A triggered alert instance."""

    __tablename__ = "alert_history"

    id = Column(Integer, primary_key=True, autoincrement=True)
    rule_id = Column(String, ForeignKey("alert_rules.rule_id"), nullable=False, index=True)
    triggered_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    metric_value = Column(Float, nullable=False)
    message = Column(Text, nullable=True)
    acknowledged = Column(Boolean, default=False, nullable=False)
    acknowledged_at = Column(DateTime, nullable=True)
    acknowledged_by = Column(String, nullable=True)

    rule = relationship("AlertRuleModel", back_populates="history")


class MetricsSnapshotModel(Base):
    """A point-in-time metric sample.

    Written by infra/monitor.py every collect_interval_seconds (default 10s).
    Queried by /api/monitor/metrics for time-series display.
    """

    __tablename__ = "metrics_snapshot"

    id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    metric_name = Column(String, nullable=False)  # cpu|memory|disk|network|task_duration|...
    metric_value = Column(Float, nullable=False)
    labels = Column(Text, nullable=True)  # JSON: {"bot_id":"bot1","task_type":"build"}

    __table_args__ = (
        Index("idx_metrics_snapshot_ts", "timestamp", "metric_name"),
    )
