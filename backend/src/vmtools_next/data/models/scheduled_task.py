"""定时任务模型（2026-08-13 任务管理页）。

定时调度 MF bot 自动执行仓库扫描 / 物流 / 地图画启动任务。
调度方式：
- once:   一次性（run_at 到点执行一次，执行后自动停用）
- daily:  每天 schedule_time（HH:MM）执行
- weekly: 每周 schedule_weekday（0=周一 ~ 6=周日）+ schedule_time 执行
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, String, Boolean, DateTime, Integer, Text

from vmtools_next.data.db import Base


class ScheduledTaskModel(Base):
    __tablename__ = "scheduled_tasks"

    id = Column(String(32), primary_key=True, default=lambda: uuid.uuid4().hex)
    name = Column(String(128), nullable=False)
    task_type = Column(String(16), nullable=False)  # scan | logistics | map_art
    target_id = Column(String(128), nullable=False)  # 仓库ID / 物流模板ID / 地图画 task_id
    target_name = Column(String(256), default="")   # 冗余展示名
    bot_ids = Column(Text, default="[]")            # JSON 数组：执行该任务的 bot 列表

    schedule_kind = Column(String(8), nullable=False)   # once | daily | weekly
    run_at = Column(DateTime, nullable=True)            # once：一次性执行时间
    schedule_time = Column(String(5), default="")       # daily/weekly：HH:MM
    schedule_weekday = Column(Integer, default=0)       # weekly：0=周一 ~ 6=周日

    enabled = Column(Boolean, default=True, nullable=False)
    last_run_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
