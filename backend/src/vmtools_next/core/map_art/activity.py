"""地图画活动日志 —— 环形缓冲 + Socket.IO 广播 + 历史回放。

重构前两套协调器各写一份 ``_activity`` / ``_on_loop_activity`` / ``emit_log_history``，
逻辑等价但字段/静默策略不一致。收敛到这里：所有 bot 与协调器日志走同一入口。
"""

from __future__ import annotations

import asyncio
import logging
from collections import deque
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger("vmtools.map_art.activity")

COORDINATOR_BOT_ID = "coordinator"
COORDINATOR_BOT_NAME = "协调器"


class ActivityLog:
    """任务级活动日志。

    - ``push``：写入环形缓冲并广播 ``build_log``（前端实时终端）
    - ``emit_history``：前端 join 房间时回放 ``build_log_history``
    - sio 不可用（测试环境 / 无事件循环）时静默降级，只写 python logging
    """

    def __init__(self, task_id: str, maxlen: int = 300, sio=None):
        self.task_id = task_id
        self._entries: deque = deque(maxlen=maxlen)
        self._sio = sio

    # ── 内部 ──

    @property
    def room(self) -> str:
        return f"build_{self.task_id}"

    def _sio_obj(self):
        if self._sio is not None:
            return self._sio
        try:
            from vmtools_next.data.db import sio  # 延迟导入，避免测试期强依赖

            return sio
        except Exception:
            return None

    def _emit(self, event: str, payload: dict) -> None:
        sio = self._sio_obj()
        if sio is None:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            # 没有事件循环（同步上下文）→ 放弃广播，日志已入缓冲
            return
        try:
            loop.create_task(sio.emit(event, payload, room=self.room))
        except Exception as e:  # pragma: no cover - 广播失败不影响建造
            logger.debug("[%s] emit %s failed: %s", self.task_id, event, e)

    # ── 对外 ──

    def push(self, level: str, message: str,
             bot_id: str = COORDINATOR_BOT_ID,
             bot_name: str = COORDINATOR_BOT_NAME) -> dict:
        entry = {
            "task_id": self.task_id,
            "bot_id": bot_id,
            "bot_name": bot_name,
            "level": level,
            "message": message,
            "ts": datetime.now(timezone.utc).isoformat(),
        }
        self._entries.append(entry)
        self._emit("build_log", entry)
        return entry

    def emit_history(self, to_room: Optional[str] = None) -> None:
        if not self._entries:
            return
        sio = self._sio_obj()
        if sio is None:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        payload = {"task_id": self.task_id, "logs": list(self._entries)}
        room = to_room or self.room
        try:
            loop.create_task(sio.emit("build_log_history", payload, room=room))
        except Exception:  # pragma: no cover
            pass

    def recent(self, limit: int = 100) -> list[dict]:
        items = list(self._entries)
        return items[-limit:]

    def __len__(self) -> int:
        return len(self._entries)
