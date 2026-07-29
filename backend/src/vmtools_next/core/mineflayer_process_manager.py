"""Mineflayer Process Manager — launches and manages Node.js mineflayer bot processes.

Replaces MccProcessManager for mineflayer backend. Manages:
  - Subprocess creation (node bot_main.js ...)
  - Process lifecycle (start/stop/restart)
  - Port allocation (reuses MccPortAllocator)
  - Auto-reconnect on crash
  - Stdout logging
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


@dataclass
class ProcessHandle:
    """Handle for a running mineflayer bot process."""
    instance_id: str
    process: asyncio.subprocess.Process
    ws_port: int
    started_at: float
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

            # 启动进程
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                env=env,
            )

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
            async for line in handle.process.stdout:
                text = line.decode("utf-8", errors="replace").rstrip()
                if text:
                    logger.debug("[%s] %s", handle.instance_id[:8], text)
                    # 检测 READY 信号
                    if "READY" in text:
                        logger.info("Mineflayer bot %s is ready (ws_port=%d)",
                                     handle.instance_id[:8], handle.ws_port)
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

    @staticmethod
    def _get_mc_host(instance: MccInstanceModel) -> str:
        return instance.mc_server_host or "127.0.0.1"

    @staticmethod
    def _get_mc_port(instance: MccInstanceModel) -> int:
        return instance.mc_server_port or 25565
