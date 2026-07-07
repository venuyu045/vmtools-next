"""In-memory terminal log buffers for MCC instances."""
from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from threading import Lock
from typing import Deque

from vmtools_next.config import get_config


@dataclass
class TerminalLine:
    instance_id: str
    seq: int
    stream: str
    content: str
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class TerminalLogBuffer:
    """Per-instance ring buffer with monotonically increasing sequence ids."""

    def __init__(self, max_lines: int | None = None):
        self.max_lines = max_lines or get_config().mcc.terminal_buffer_lines
        self._buffers: dict[str, Deque[TerminalLine]] = defaultdict(lambda: deque(maxlen=self.max_lines))
        self._seq: dict[str, int] = defaultdict(int)
        self._lock = Lock()

    def append(self, instance_id: str, stream: str, content: str) -> TerminalLine:
        with self._lock:
            self._seq[instance_id] += 1
            line = TerminalLine(
                instance_id=instance_id,
                seq=self._seq[instance_id],
                stream=stream,
                content=content,
            )
            self._buffers[instance_id].append(line)
            return line

    def tail(self, instance_id: str, count: int = 500, after_seq: int | None = None) -> list[TerminalLine]:
        with self._lock:
            lines = list(self._buffers.get(instance_id, []))
        if after_seq is not None:
            lines = [line for line in lines if line.seq > after_seq]
        return lines[-max(0, count):]

    def last_seq(self, instance_id: str) -> int:
        with self._lock:
            return self._seq.get(instance_id, 0)

    def sync_seq(self, instance_id: str, seq: int) -> None:
        with self._lock:
            self._seq[instance_id] = max(self._seq.get(instance_id, 0), seq)
