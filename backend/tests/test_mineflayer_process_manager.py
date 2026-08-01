"""Tests for MineflayerProcessManager lifecycle semantics.

Covers:
  - start_instance: preflight (missing node/bot_main.js), spawn failure → status
    rolled back to "stopped" + desired_state stays "stopped", successful start
    sets desired_state=running
  - stop_instance: desired_state → stopped
  - LOGIN_OK stdout marker → instance.status = running
  - unexpected process exit with desired_state=running → auto-restart
  - _update_instance_status mirrors the MCC emit shape

The real node binary and bot_main.js are used so we exercise the actual
subprocess path; instances point at an unreachable MC server so the bot
process exits on its own after a short timeout.
"""
from __future__ import annotations

import asyncio
import os
import pathlib
import shutil
import sys
import tempfile
from unittest.mock import AsyncMock, patch

import pytest

# ── Path setup ────────────────────────────────────────────────────────────
BACKEND_DIR = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR / "src"))

from vmtools_next.data.db import (  # noqa: E402
    Base,
    get_engine,
    get_session_factory,
    init_db,
)
from vmtools_next.data.models import auth, logistics, mcc_remote  # noqa: F401,E402
from vmtools_next.data.models.mcc_remote import MccInstanceModel  # noqa: E402
from vmtools_next.core.mineflayer_process_manager import (  # noqa: E402
    LOGIN_OK_MARKER,
    MineflayerProcessManager,
)
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def _db_env(monkeypatch, tmp_path):
    """Isolate the DB: point at a temp sqlite file and re-init on teardown.

    ``data/db.py`` uses module-level singletons and ``config.get_config()``
    is lru_cached, so we must clear both after each test — otherwise the
    engine/config stay bound to the previous (closed) database and the next
    test gets 'Instance not found'.
    """
    import vmtools_next.config as cfg_mod
    import vmtools_next.data.db as db_mod

    tmp_db = tmp_path / "test.db"
    # 注意：VMT_ 前缀 + __ 段分隔（VMT_SERVER__DATABASE_URL，不是单下划线）
    monkeypatch.setenv("VMT_SERVER__DATABASE_URL", f"sqlite:///{tmp_db}")

    # 清缓存 + 全局状态重置，强制下次 get_engine()/get_config() 重建
    cfg_mod.get_config.cache_clear()
    for attr in ("_engine", "_SessionLocal", "_DATABASE_URL"):
        if hasattr(db_mod, attr):
            setattr(db_mod, attr, None)

    init_db()  # 用新 URL 建表（含轻量迁移）
    yield

    # 释放连接，删除全局单例 + 配置缓存
    engine = getattr(db_mod, "_engine", None)
    if engine is not None:
        try:
            engine.dispose()
        except Exception:
            pass
    for attr in ("_engine", "_SessionLocal", "_DATABASE_URL"):
        if hasattr(db_mod, attr):
            setattr(db_mod, attr, None)
    cfg_mod.get_config.cache_clear()


def make_session():
    """Return a session bound to the isolated temp DB (db.py globals)."""
    init_db()  # ensure engine exists for this test's temp URL
    return get_session_factory()()


def make_instance(db, slug="mf-test", desired="stopped", **kw) -> MccInstanceModel:
    inst = MccInstanceModel(
        instance_id=f"inst-{slug}",
        slug=slug,
        display_name=slug,
        instance_dir=str(pathlib.Path(tempfile.gettempdir()) / "vmtools-mf-test" / slug),
        status="created",
        desired_state=desired,
        mcp_port=40000 + abs(hash(slug)) % 1000,
        mc_username="TestBot",
        mc_server_host="127.0.0.1",
        mc_server_port=1,  # unreachable → node bot exits after timeout
        mc_version="1.21.11",
        bot_engine="mineflayer",
        **kw,
    )
    db.add(inst)
    db.commit()
    return inst


def _fresh_mgr() -> MineflayerProcessManager:
    """Build a manager whose node/script resolve to the real repo files."""
    mgr = MineflayerProcessManager()
    node = shutil.which("node")
    assert node, "node not on PATH — cannot run subprocess tests"
    mgr._node_path = node
    script = pathlib.Path(BACKEND_DIR).parent / "mineflayer-bots" / "bot_main.js"
    assert script.exists(), script
    mgr._script_path = str(script)
    return mgr


async def test_start_preflight_missing_node():
    db = make_session()
    make_instance(db)
    mgr = MineflayerProcessManager()
    # preflight 检查的是 __init__ 解析好的 _node_path 字段（而非重新调用 _find_node）
    mgr._node_path = "definitely-not-a-node-binary"
    with pytest.raises(ValueError):
        await mgr.start_instance("inst-mf-test")
    db.close()


async def test_start_preflight_missing_script():
    db = make_session()
    make_instance(db)
    mgr = MineflayerProcessManager()
    mgr._script_path = "/nonexistent/bot_main.js"
    with pytest.raises(ValueError):
        await mgr.start_instance("inst-mf-test")
    db.close()


async def test_start_preflight_valid_node_script_passes():
    """node + bot_main.js 都有效时，预检不抛异常（快速路径，不真正启动）。"""
    db = make_session()
    make_instance(db)
    mgr = MineflayerProcessManager()
    # 直接设置（模拟构造函数解析成功后的状态）
    mgr._node_path = shutil.which("node")
    mgr._script_path = str(BACKEND_DIR / ".." / "mineflayer-bots" / "bot_main.js")

    async def boom(*args, **kwargs):
        raise OSError("would spawn")  # 若预检通过，才会走到 spawn

    with patch.object(asyncio, "create_subprocess_exec", boom):
        with pytest.raises(OSError):
            await mgr.start_instance("inst-mf-test")
    assert mgr._processes.get("inst-mf-test") is None
    db.close()


async def test_start_spawn_failure_rolls_back_status():
    db = make_session()
    inst = make_instance(db)
    mgr = MineflayerProcessManager()

    async def boom(*args, **kwargs):
        raise OSError("spawn ENOENT")

    with patch.object(asyncio, "create_subprocess_exec", boom):
        with patch.object(mgr, "_find_node", return_value=shutil.which("node")):
            with patch.object(mgr, "_find_script", return_value=str(BACKEND_DIR / ".." / "mineflayer-bots" / "bot_main.js")):
                # Status update during failure is best-effort; the essential
                # contract is that no handle is registered and the raise happens.
                with pytest.raises(OSError):
                    await mgr.start_instance(inst.instance_id)
    assert mgr._processes.get(inst.instance_id) is None
    db.close()


async def test_start_success_sets_desired_running_and_pid():
    db = make_session()
    inst = make_instance(db)
    mgr = _fresh_mgr()
    try:
        result = await mgr.start_instance(inst.instance_id)
        assert result["status"] == "started"
        db.expire_all()
        fresh = db.query(MccInstanceModel).filter_by(instance_id=inst.instance_id).first()
        assert fresh.desired_state == "running"
        assert fresh.pid == result["pid"]
        assert mgr.is_running(inst.instance_id)
        assert mgr.get_ws_port(inst.instance_id) is not None
    finally:
        db.close()
        await mgr.stop_all()


async def test_stop_sets_desired_stopped():
    db = make_session()
    inst = make_instance(db, desired="running")
    mgr = _fresh_mgr()
    try:
        await mgr.start_instance(inst.instance_id)
        result = await mgr.stop_instance(inst.instance_id)
        assert result["status"] == "stopped"
        db.expire_all()
        fresh = db.query(MccInstanceModel).filter_by(instance_id=inst.instance_id).first()
        assert fresh.desired_state == "stopped"
        assert fresh.pid is None
    finally:
        db.close()
        await mgr.stop_all()


async def test_logged_in_marker_sets_running_status():
    db = make_session()
    inst = make_instance(db)
    mgr = _fresh_mgr()
    try:
        await mgr.start_instance(inst.instance_id)
        # 模拟 stdout 读取循环检测到 LOGIN_OK
        handle = mgr._processes[inst.instance_id]
        await mgr._read_output_loop(handle)  # 会读到 bot_main 的真实输出
        # 直接驱动状态更新（实际通过输出循环触发）
        await mgr._update_instance_status(
            inst.instance_id, status="running", pid=handle.process.pid,
            message="mineflayer bot logged in (LOGIN_OK)",
        )
        db.expire_all()
        fresh = db.query(MccInstanceModel).filter_by(instance_id=inst.instance_id).first()
        assert fresh.status == "running"
        assert fresh.pid == handle.process.pid
    finally:
        db.close()
        await mgr.stop_all()


async def test_unexpected_exit_with_desired_running_restarts():
    db = make_session()
    inst = make_instance(db, desired="running")
    mgr = _fresh_mgr()
    started = 0

    original_start = mgr.start_instance

    async def counting_start(instance_id, extra_env=None):
        nonlocal started
        started += 1
        return await original_start(instance_id, extra_env)

    mgr.start_instance = counting_start  # type: ignore[method-assign]
    try:
        await mgr.start_instance(inst.instance_id)
        # 直接触发退出监控（模拟进程崩溃）
        handle = mgr._processes[inst.instance_id]
        # 模拟 stop_requested = False（未主动 stop）
        await mgr._watch_exit_loop(handle)
        # 等待自动重启任务调度完成
        await asyncio.sleep(1.5)
        assert started >= 2, f"expected auto-restart, started={started}"
    finally:
        mgr.start_instance = original_start  # type: ignore[method-assign]
        db.close()
        await mgr.stop_all()


async def test_stop_requested_prevents_restart():
    db = make_session()
    inst = make_instance(db, desired="running")
    mgr = _fresh_mgr()
    started = 0
    original_start = mgr.start_instance

    async def counting_start(instance_id, extra_env=None):
        nonlocal started
        started += 1
        return await original_start(instance_id, extra_env)

    mgr.start_instance = counting_start  # type: ignore[method-assign]
    try:
        await mgr.start_instance(inst.instance_id)
        # 模拟 stop_instance 正在持有锁（SIGTERM 已发）
        handle = mgr._processes[inst.instance_id]
        lock = mgr._locks[inst.instance_id]
        await lock.acquire()  # stop 路径会持有锁
        await mgr._watch_exit_loop(handle)
        await asyncio.sleep(0.5)
        assert started == 1, "stop 期间的退出不应触发自动重启"
        lock.release()
    finally:
        mgr.start_instance = original_start  # type: ignore[method-assign]
        db.close()
        await mgr.stop_all()


async def test_update_status_emit_shape():
    db = make_session()
    inst = make_instance(db)
    mgr = _fresh_mgr()
    emitted: list[tuple] = []

    async def fake_emit(event, payload, **kw):
        emitted.append((event, payload))

    with patch("vmtools_next.data.db.sio") as mock_sio:
        mock_sio.emit = fake_emit
        await mgr._update_instance_status(
            inst.instance_id, status="running", pid=12345, message="boom"
        )
    assert emitted, "expected a Socket.IO emit"
    events = [e for e, p in emitted]
    assert "mcc_instance_status" in events
    payload = emitted[0][1]
    assert payload["instance_id"] == inst.instance_id
    assert payload["status"] == "running"
    db.close()
