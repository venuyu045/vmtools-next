"""Mineflayer Process Manager — launches and manages Node.js mineflayer bot processes.

Replaces MccProcessManager for mineflayer backend. Manages:
  - Subprocess creation (node bot_main.js ...)
  - Process lifecycle (start/stop/restart)
  - Port allocation (reuses MccPortAllocator)
  - Auto-reconnect on crash
  - Stdout logging
  - Status sync: instance.status + bot login flag + Socket.IO broadcast
"""

from __future__ import annotations

import asyncio
import logging
import os
import pathlib
import shutil
import signal
import time
from dataclasses import dataclass, field
from typing import Optional

from sqlalchemy.orm import Session

from vmtools_next.config import get_config
from vmtools_next.core.mcc_port_allocator import MccPortAllocator
from vmtools_next.data.models.mcc_remote import MccAccountProfileModel, MccInstanceModel, MccProcessEventModel

logger = logging.getLogger("vmtools.mineflayer_pm")

# 登录成功标志：bot_main.js 在 mineflayer login 事件里打印（作为 bot 真正进入服务器的确定性信号）
LOGIN_OK_MARKER = "LOGIN_OK"


@dataclass
class ProcessHandle:
    """Handle for a running mineflayer bot process."""
    instance_id: str
    process: asyncio.subprocess.Process
    ws_port: int
    started_at: float
    logged_in: bool = False
    output_task: Optional[asyncio.Task] = None
    exit_task: Optional[asyncio.Task] = None
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


class MineflayerProcessManager:
    """Manages Node.js mineflayer bot subprocesses."""

    def __init__(self):
        config = get_config().mcc  # 复用 MCC 配置的 instance_root 等，WS 端口用新范围
        self._instance_root = pathlib.Path(config.instance_root)
        self._processes: dict[str, ProcessHandle] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        self._port_allocator = MccPortAllocator(
            start_port=getattr(config, 'mineflayer_ws_start_port', 44444),
            end_port=getattr(config, 'mineflayer_ws_end_port', 44500),
        )
        self._node_path = self._find_node()
        self._script_path = self._find_script()

    @staticmethod
    def _find_node() -> str:
        """Find the Node.js executable (cross-platform)."""
        node = shutil.which("node")
        if node:
            return node
        for candidate in ["/usr/bin/node", "/usr/local/bin/node"]:
            if os.access(candidate, os.X_OK):
                return candidate
        # 兜底：靠 PATH
        return "node"

    def _find_script(self) -> str:
        """Find bot_main.js relative to the project."""
        # 文件路径：.../vmtools_next/core/mineflayer_process_manager.py
        # 从 core/ → vmtools_next/ → src/ → backend/ → project-root/ 计 4 层
        here = pathlib.Path(__file__).resolve().parent  # vmtools_next/core/
        project_root = here.parent.parent.parent.parent  # 项目根目录
        candidate = project_root / "mineflayer-bots" / "bot_main.js"
        if candidate.exists():
            return str(candidate.resolve())
        # fallback: 可能 CWD 是 backend/，往上一层
        cwd = pathlib.Path(os.getcwd())
        candidate2 = cwd.parent / "mineflayer-bots" / "bot_main.js"
        if candidate2.exists():
            return str(candidate2.resolve())
        return str(candidate)  # 实在找不到就给路径，让启动时报错

    def is_running(self, instance_id: str) -> bool:
        """Check if a mineflayer process is running."""
        handle = self._processes.get(instance_id)
        if handle is None:
            return False
        return handle.process.returncode is None

    async def start_instance(self, instance_id: str,
                              extra_env: dict[str, str] | None = None) -> dict:
        """Start a mineflayer bot process for the given instance."""
        lock = self._locks.setdefault(instance_id, asyncio.Lock())
        async with lock:
            if self.is_running(instance_id):
                handle = self._processes[instance_id]
                return {"status": "running", "pid": handle.process.pid,
                        "ws_port": handle.ws_port, "message": "already running"}

            # 从数据库加载实例
            from vmtools_next.data.db import get_session_factory
            Session = get_session_factory()
            db = Session()
            try:
                instance = db.query(MccInstanceModel).filter(
                    MccInstanceModel.instance_id == instance_id,
                    MccInstanceModel.deleted_at.is_(None),
                ).first()
                if not instance:
                    raise ValueError("Instance not found")
            finally:
                db.close()

            # 启动前预检：node 可执行 + bot_main.js 存在（否则 create_subprocess_exec 会失败）
            # 注意：self._node_path 可能是绝对路径，which() 只查 PATH；同时检查可执行性
            node_ok = self._node_path and (
                os.path.isabs(self._node_path) and os.access(self._node_path, os.X_OK)
                or shutil.which(self._node_path)
            )
            if not node_ok:
                raise ValueError(f"Node.js executable not found: {self._node_path!r}")
            if not self._script_path or not os.path.exists(self._script_path):
                raise ValueError(f"bot_main.js not found: {self._script_path!r}")

            # 分配 WS 端口
            db_session = Session()
            try:
                ws_port = self._port_allocator.allocate(db_session)
            finally:
                db_session.close()

            # 加载关联的账号配置（如果有）
            account_profile = None
            if instance.account_profile_id:
                try:
                    Session2 = get_session_factory()
                    db2 = Session2()
                    account_profile = db2.query(MccAccountProfileModel).filter(
                        MccAccountProfileModel.profile_id == instance.account_profile_id,
                    ).first()
                finally:
                    db2.close()

            # 构建启动命令
            cmd = [
                self._node_path,
                self._script_path,
                "--ws-port", str(ws_port),
                "--mc-host", self._get_mc_host(instance),
                "--mc-port", str(self._get_mc_port(instance)),
                "--username", instance.mc_username or instance.instance_id,
                "--version", instance.mc_version or "1.21.11",
            ]

            # ── 认���方式处理 ──
            auth_type = account_profile.auth_type if account_profile else "offline"

            if auth_type == "yggdrasil":
                cmd += ["--auth", "yggdrasil"]

                # yggdrasil 登录使用账号的 username（邮箱），不是游戏内名字
                if account_profile and account_profile.username:
                    cmd[9] = account_profile.username  # 替换 --username 的值

                # 从账号配置获取 auth server URL
                auth_url = account_profile.auth_server_url if account_profile else ""
                if not auth_url:
                    mf_config = get_config().mineflayer
                    auth_url = getattr(mf_config, "yggdrasil_auth_server_url", "")
                if auth_url:
                    cmd += ["--auth-server-url", auth_url]

                if account_profile and account_profile.password_secret:
                    cmd += ["--password", account_profile.password_secret]
            else:
                cmd += ["--auth", auth_type]
                if account_profile and account_profile.password_secret:
                    cmd += ["--password", account_profile.password_secret]

            # 环境变量
            env = os.environ.copy()
            env["VMT_INSTANCE_ID"] = instance.instance_id
            if extra_env:
                env.update({str(k): str(v) for k, v in extra_env.items()})

            logger.info("Starting mineflayer bot: %s", " ".join(cmd[:6]) + " ...")

            # 启动进程（失败 → 弹回 stopped，与 MCC start_instance 的语义一致）
            try:
                process = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.STDOUT,
                    env=env,
                )
            except Exception as exc:
                logger.error("Failed to spawn mineflayer bot %s: %s", instance_id[:8], exc)
                await self._update_instance_status(
                    instance_id, status="stopped", pid=None,
                    message=f"mineflayer spawn failed: {str(exc) or repr(exc)}",
                )
                raise

            handle = ProcessHandle(
                instance_id=instance_id,
                process=process,
                ws_port=ws_port,
                started_at=time.time(),
            )
            self._processes[instance_id] = handle

            # 启动 stdout 读取和退出监控
            handle.output_task = asyncio.create_task(
                self._read_output_loop(handle)
            )
            handle.exit_task = asyncio.create_task(
                self._watch_exit_loop(handle)
            )

            # 同步实例状态到 DB + Socket.IO（desired_state 由 _sync_desired_state 管理）
            await self._update_instance_status(
                instance_id,
                status="starting",
                pid=process.pid,
                message=f"mineflayer process started (ws_port={ws_port})",
            )
            await self._sync_desired_state(instance_id, "running")

            return {
                "status": "started",
                "pid": process.pid,
                "ws_port": ws_port,
            }

    async def stop_instance(self, instance_id: str,
                             force: bool = False,
                             timeout_seconds: float = 10.0) -> dict:
        """Stop a mineflayer bot process gracefully."""
        handle = self._processes.get(instance_id)
        if not handle or handle.process.returncode is not None:
            # 进程可能已自行退出；无论如何确保 desired_state = stopped
            await self._sync_desired_state(instance_id, "stopped")
            return {"status": "not_running"}

        try:
            # 先尝试 SIGTERM
            if hasattr(signal, 'SIGTERM'):
                handle.process.send_signal(signal.SIGTERM)
            else:
                handle.process.terminate()

            try:
                await asyncio.wait_for(handle.process.wait(), timeout=timeout_seconds)
            except asyncio.TimeoutError:
                handle.process.kill()
                await handle.process.wait()

        except ProcessLookupError:
            pass

        # 清理
        self._cleanup_handle(instance_id)

        # 同步状态：DB + Socket.IO
        await self._sync_desired_state(instance_id, "stopped")
        await self._update_instance_status(
            instance_id,
            status="stopped",
            pid=None,
            message="mineflayer process stopped",
        )

        return {"status": "stopped"}

    async def stop_all(self) -> None:
        """Stop all mineflayer bot processes."""
        for instance_id in list(self._processes.keys()):
            await self.stop_instance(instance_id)

    def get_ws_port(self, instance_id: str) -> Optional[int]:
        """Get the WebSocket port for a running bot."""
        handle = self._processes.get(instance_id)
        if handle and handle.process.returncode is None:
            return handle.ws_port
        return None

    # ── 内部方法 ──

    async def _read_output_loop(self, handle: ProcessHandle) -> None:
        """Read stdout from the mineflayer process line by line."""
        try:
            # 用 readline 而非 async for —— Windows Proactor 下 async for 对
            # PIPE 的迭代可能不会逐行触发（缓冲问题），readline 稳定。
            while True:
                line = await handle.process.stdout.readline()
                if not line:
                    break
                text = line.decode("utf-8", errors="replace").rstrip()
                if text:
                    logger.debug("[%s] %s", handle.instance_id[:8], text)
                    # 检测 READY 信号
                    if "READY" in text:
                        logger.info("Mineflayer bot %s is ready (ws_port=%d)",
                                     handle.instance_id[:8], handle.ws_port)
                    # 检测登录成功信号 → 同步 instance.status = running
                    if LOGIN_OK_MARKER in text and not handle.logged_in:
                        handle.logged_in = True
                        logger.info("Mineflayer bot %s logged in (LOGIN_OK)",
                                    handle.instance_id[:8])
                        await self._update_instance_status(
                            handle.instance_id,
                            status="running",
                            pid=handle.process.pid,
                            message="mineflayer bot logged in (LOGIN_OK)",
                        )
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error("Output read error for %s: %s", handle.instance_id[:8], e)

    async def _watch_exit_loop(self, handle: ProcessHandle) -> None:
        """Monitor the process for unexpected exits and auto-restart."""
        try:
            return_code = await handle.process.wait()
        except asyncio.CancelledError:
            return

        instance_id = handle.instance_id
        logger.warning("Mineflayer bot %s exited with code %d",
                        instance_id[:8], return_code)

        # 记录事件
        await self._record_event(instance_id, f"Process exited: code {return_code}")

        # 清理
        if self._processes.get(instance_id) is handle:
            self._processes.pop(instance_id, None)

        # 同步状态：进程退出 → stopped
        await self._update_instance_status(
            instance_id,
            status="stopped",
            pid=None,
            message=f"mineflayer process exited (code {return_code})",
        )

        # 意外退出（非 stop_instance 主动终止）且实例仍期望运行 → 自动重启，
        # 与 MccProcessManager 的 auto_reconnect/desired_state 语义一致。
        try:
            if not self._stop_requested(instance_id):
                if await self._desired_state_is(instance_id, "running"):
                    logger.warning(
                        "Mineflayer bot %s crashed unexpectedly, auto-restarting (desired_state=running)",
                        instance_id[:8],
                    )
                    await self.start_instance(instance_id)
        except Exception as exc:
            logger.warning("Auto-restart failed for %s: %s", instance_id[:8], exc)

    async def _desired_state_is(self, instance_id: str, state: str) -> bool:
        """Check the instance's desired_state in the DB."""
        from vmtools_next.data.db import get_session_factory
        Session = get_session_factory()
        db = Session()
        try:
            inst = db.query(MccInstanceModel).filter(
                MccInstanceModel.instance_id == instance_id,
            ).first()
            return bool(inst and inst.desired_state == state)
        finally:
            db.close()

    def _stop_requested(self, instance_id: str) -> bool:
        """True while stop_instance is still holding the instance lock (SIGTERM sent)."""
        lock = self._locks.get(instance_id)
        return bool(lock and lock.locked())

    async def _sync_desired_state(self, instance_id: str, state: str) -> None:
        """Persist desired_state (running on start, stopped on stop)."""
        try:
            from vmtools_next.data.db import get_session_factory
            Session = get_session_factory()
            db = Session()
            try:
                inst = db.query(MccInstanceModel).filter(
                    MccInstanceModel.instance_id == instance_id,
                ).first()
                if inst and inst.desired_state != state:
                    inst.desired_state = state
                    db.commit()
            finally:
                db.close()
        except Exception as e:
            logger.warning("Failed to sync desired_state for %s: %s", instance_id, e)

    def _cleanup_handle(self, instance_id: str) -> None:
        """Remove and clean up a process handle."""
        handle = self._processes.pop(instance_id, None)
        if handle:
            # 取消后台任务
            for task_name in ["output_task", "exit_task"]:
                task = getattr(handle, task_name, None)
                if task and not task.done():
                    task.cancel()

    @staticmethod
    async def _record_event(instance_id: str, message: str) -> None:
        """Record a process event in the database."""
        try:
            from vmtools_next.data.db import get_session_factory
            Session = get_session_factory()
            db = Session()
            try:
                event = MccProcessEventModel(
                    instance_id=instance_id,
                    event_type="process",
                    message=message,
                    created_at=time.time(),
                )
                db.add(event)
                db.commit()
            finally:
                db.close()
        except Exception as e:
            logger.warning("Failed to record event: %s", e)

    async def _update_instance_status(self, instance_id: str, status: str,
                                      pid: int | None, message: str = "") -> None:
        """Sync instance status to DB and broadcast via Socket.IO.

        Mirrors MccProcessManager._emit_status so the frontend reacts the same way.
        """
        try:
            from vmtools_next.data.db import get_session_factory, sio
            Session = get_session_factory()
            db = Session()
            try:
                instance = db.query(MccInstanceModel).filter(
                    MccInstanceModel.instance_id == instance_id,
                    MccInstanceModel.deleted_at.is_(None),
                ).first()
                if instance:
                    instance.status = status
                    instance.pid = pid
                    # SQLAlchemy DateTime 列必须用 datetime 对象（字符串会 TypeError）
                    from datetime import datetime as _dt
                    if status == "running":
                        instance.last_started_at = _dt.now()
                    if status == "stopped":
                        instance.last_stopped_at = _dt.now()
                    db.commit()
            finally:
                db.close()

            payload = {
                "instance_id": instance_id,
                "status": status,
                "pid": pid,
                "ws_port": self.get_ws_port(instance_id) if pid else None,
                "message": message,
            }
            # 房间内 + 全局广播（前端按 instance_id 去重）
            # sio.emit 在没有 socket server（如单元测试/独立脚本）时会抛异常，需保护
            try:
                await sio.emit("mcc_instance_status", payload, room=f"mcc:{instance_id}")
                await sio.emit("mcc_instance_status", payload)
            except Exception as emit_err:
                logger.debug("Socket.IO emit skipped: %s", emit_err)
        except Exception as e:
            logger.warning("Failed to sync status for %s: %s", instance_id, e)

    @staticmethod
    def _get_mc_host(instance: MccInstanceModel) -> str:
        return instance.mc_server_host or "127.0.0.1"

    @staticmethod
    def _get_mc_port(instance: MccInstanceModel) -> int:
        return instance.mc_server_port or 25565
