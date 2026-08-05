"""Regression tests for the terminal pipeline fixes.

Covers: ANSI sanitizing, tail_logs DB padding, write_stdin command routing and
the disconnect-pending blank-line guard.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from vmtools_next.core.mcc_process_manager import MccProcessManager, ProcessHandle
from vmtools_next.core.terminal_log_buffer import TerminalLogBuffer


def test_sanitize_ansi_keeps_sgr_strips_cursor_sequences():
    s = MccProcessManager._sanitize_ansi
    # SGR color/style sequences are preserved
    assert s("hello\x1b[31mred\x1b[0m world") == "hello\x1b[31mred\x1b[0m world"
    # 24-bit SGR preserved
    assert s("ok\x1b[38;2;255;0;0m rgb\x1b[0m") == "ok\x1b[38;2;255;0;0m rgb\x1b[0m"
    # clear-screen / cursor-move / cursor-visibility are stripped
    assert s("\x1b[2Jclear") == "clear"
    assert s("a\x1b[1Aup") == "aup"
    assert s("x\x1b[?25lhide") == "xhide"
    assert s("line\x1b[Kend") == "lineend"


def test_tail_logs_pads_from_db_when_buffer_short(monkeypatch):
    """Buffer holds fewer lines than requested -> older rows come from DB."""
    import vmtools_next.core.mcc_process_manager as mpm

    manager = MccProcessManager()
    # buffer only has the 3 most recent lines
    manager.buffer = TerminalLogBuffer(max_lines=50)
    for seq in (8, 9, 10):
        manager.buffer.append("inst", "stdout", f"line {seq}")

    class FakeRow:
        def __init__(self, seq):
            self.seq = seq
            self.instance_id = "inst"
            self.stream = "stdout"
            self.content = f"db-line {seq}"
            self.content_masked = None
            self.created_at = None

    class FakeQuery:
        def __init__(self, rows):
            self.rows = rows

        def filter(self, *a, **k):
            return self

        def order_by(self, *a, **k):
            return self

        def limit(self, n):
            return self

        def all(self):
            return self.rows

    class FakeDB:
        def query(self, model):
            return FakeQuery([FakeRow(i) for i in range(1, 11)])

        def close(self):
            pass

    monkeypatch.setattr(mpm, "get_session_factory", lambda: FakeDB)

    lines = manager.tail_logs("inst", tail=8)
    seqs = [line.seq for line in lines]
    # 8 newest after merging DB rows 1..10 with buffer rows 8..10 (deduped)
    assert seqs == [3, 4, 5, 6, 7, 8, 9, 10], seqs


def test_tail_logs_uses_buffer_when_enough_lines():
    """Buffer already covering the window avoids a DB round-trip."""
    manager = MccProcessManager()
    manager.buffer = TerminalLogBuffer(max_lines=50)
    for seq in range(1, 11):
        manager.buffer.append("inst", "stdout", f"line {seq}")
    lines = manager.tail_logs("inst", tail=8)
    assert [line.seq for line in lines] == [3, 4, 5, 6, 7, 8, 9, 10]


class _FakeStdin:
    def __init__(self):
        self.written: list[bytes] = []

    def write(self, data: bytes):
        self.written.append(data)

    def flush(self):
        pass

    async def drain(self):
        pass


class _FakeProcess:
    returncode = None
    pid = 1

    def __init__(self):
        self.stdin = _FakeStdin()
        self.stdout = object()  # no readline -> treated as non-async proc


@pytest.mark.asyncio
async def test_write_stdin_routing(monkeypatch):
    """Plain text -> chat (say stripped); /commands & internal commands kept."""
    manager = MccProcessManager()
    proc = _FakeProcess()
    manager._processes["inst"] = ProcessHandle(
        instance_id="inst", process=proc, output_task=None, exit_task=None
    )

    captured: list[tuple[str, str]] = []

    async def fake_append(instance_id, stream, content, from_sid=None):
        captured.append((stream, content))

    manager._append_line = fake_append  # type: ignore[method-assign]

    async def run(input_text: str) -> bytes:
        proc.stdin.written.clear()
        await manager.write_stdin("inst", input_text)
        return b"".join(proc.stdin.written)

    # plain chat text -> say stripped before writing
    assert await run("hello world") == b"hello world\n"
    # explicit say -> still stripped (MCC auto-chats stdin lines)
    assert await run("say hi") == b"hi\n"
    # server command passed through
    assert await run("/home") == b"/home\n"
    # internal command passed through
    assert await run("status") == b"status\n"

    # all four are audited into the terminal as stdin lines
    assert [c[0] for c in captured] == ["stdin"] * 4


@pytest.mark.asyncio
async def test_detect_disconnect_blank_line_does_not_consume_pending():
    """A blank line must not consume the pending kick-reason marker."""
    manager = MccProcessManager()
    manager._pending_disconnect["inst"] = "Disconnected by Server"
    await manager._detect_disconnect("inst", "")
    assert "inst" in manager._pending_disconnect

    # A meaningful line consumes the marker (notifications are mocked away by
    # the fact that the marker is consumed before notify_mcc_event is reached).
    await manager._detect_disconnect("inst", "You have been kicked: reason")
    assert "inst" not in manager._pending_disconnect
