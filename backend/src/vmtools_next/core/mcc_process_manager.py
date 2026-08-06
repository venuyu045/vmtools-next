"""Async process manager for local/container MCC instances."""
from __future__ import annotations

import asyncio
import json
import os
import signal
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from vmtools_next.adapters.mcc.mcc_mcp_client import MccMcpClient
from vmtools_next.config import get_config
from vmtools_next.core.mcc_security import mask_text
from vmtools_next.core.terminal_log_buffer import TerminalLogBuffer, TerminalLine
from vmtools_next.data.db import get_session_factory, sio
from vmtools_next.data.models.mcc_remote import (
    MccInstanceModel,
    MccProcessEventModel,
    MccTerminalLogModel,
)
from vmtools_next.infra.logging import get_logger

logger = get_logger("mcc.process")


@dataclass
class ProcessHandle:
    instance_id: str
    process: "asyncio.subprocess.Process | subprocess.Popen"
    output_task: asyncio.Task
    exit_task: asyncio.Task | None = None
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


def _is_async_proc(proc) -> bool:
    """Check if a process object is an asyncio subprocess (has async stdout)."""
    import asyncio as _asyncio
    return hasattr(proc.stdout, "readline") and _asyncio.iscoroutinefunction(proc.stdout.readline)


class MccProcessManager:
    """Manage MCC child processes and stream their terminal output."""

    def __init__(self, buffer: TerminalLogBuffer | None = None):
        self.config = get_config().mcc
        self.buffer = buffer or TerminalLogBuffer()
        self._processes: dict[str, ProcessHandle] = {}
        self._pending_disconnect: dict[str, str] = {}  # instance_id → disconnect line
        self._pending_reconnect: dict[str, str] = {}   # instance_id → mc_username (auto-reconnect in progress)
        self._locks: dict[str, asyncio.Lock] = {}
        self._started = False
        self._sentinel_id: str | None = None  # cached sentinel instance UUID

        # Serialized terminal-event detection (per instance): stdout lines are
        # pushed to a queue and consumed strictly in order, so disconnect/kick
        # reason matching never races across lines.
        self._detection_queues: dict[str, asyncio.Queue[str]] = {}
        self._detection_tasks: dict[str, asyncio.Task] = {}

        # Batched DB persistence: lines are accumulated and flushed every 0.5s
        # (or on process exit) instead of one transaction per line.
        self._pending_db: dict[str, list] = {}
        self._db_flush_tasks: dict[str, asyncio.Task] = {}

    async def start(self) -> None:
        self._started = True
        await self._mark_stale_running_instances()
        await self._recover_desired_running_instances()

    async def stop(self) -> None:
        for instance_id in list(self._processes.keys()):
            try:
                # shutdown 场景保留 desired_state（running 实例重启后自动恢复），
                # 与 MineflayerProcessManager 的 preserve_desired_state 语义对齐。
                await self.stop_instance(instance_id, force=True, timeout_seconds=2,
                                         preserve_desired_state=True)
            except Exception as exc:
                logger.warning("Failed to stop MCC instance {} during shutdown: {}", instance_id, exc)
        self._started = False

    async def stop_all_instances(self, force: bool = True, timeout_seconds: float = 5.0,
                                 include_sweep: bool = True) -> dict:
        """Force-kill all running MCC processes (tracked + orphaned). Returns summary dict."""
        results: list[dict] = []
        killed_pids: set[int] = set()

        # 1. Kill tracked processes in PARALLEL — serial kills would take
        #    N×timeout_seconds worst case and blow past HTTP client timeouts
        #    (frontend axios default 15s) on multi-instance setups.
        async def _kill_tracked(instance_id: str) -> dict:
            try:
                result = await self.stop_instance(instance_id, force=force, timeout_seconds=timeout_seconds)
                return {"instance_id": instance_id, "status": result.get("status", "unknown"), "message": result.get("message", "")}
            except Exception as exc:
                logger.warning("Failed to force-kill MCC instance {}: {}", instance_id, exc)
                return {"instance_id": instance_id, "status": "error", "message": str(exc) or repr(exc)}

        tracked_ids = list(self._processes.keys())
        if tracked_ids:
            results.extend(await asyncio.gather(*(_kill_tracked(iid) for iid in tracked_ids)))

        # 2. Kill orphaned processes by scanning system process table
        #    (handles backend-restart scenarios where _processes is empty and DB status is stale).
        #    include_sweep=False 用于 kill-all 多引擎场景，避免重复全进程扫描。
        if include_sweep:
            self._sweep_orphan_processes(killed_pids, results)

        # 3. Update DB: mark all instances as stopped
        Session2 = get_session_factory()
        db2 = Session2()
        try:
            db2.query(MccInstanceModel).filter(
                MccInstanceModel.status.in_(["running", "stopping"]),
            ).update({"status": "stopped", "pid": None, "exit_code": None, "last_stopped_at": datetime.now(timezone.utc)}, synchronize_session=False)
            db2.commit()
        except Exception as exc:
            logger.warning("Error updating DB after force-kill: {}", exc)
            db2.rollback()
        finally:
            db2.close()

        return {"killed": len(results), "results": results}

    def is_running(self, instance_id: str) -> bool:
        handle = self._processes.get(instance_id)
        if not handle:
            return False
        proc = handle.process
        return proc.returncode is None

    def _sweep_orphan_processes(self, known_pids: set[int], results: list[dict]) -> None:
        """Scan system process table for leftover MCC processes and kill them.

        Handles backend-restart scenarios where _processes is empty and DB status is stale.
        Mutates `known_pids` and appends kill records to `results`.
        """
        import psutil  # local import: tracked-kill step must run even if psutil is missing
        Session = get_session_factory()
        db = Session()
        try:
            all_instances = db.query(MccInstanceModel).all()
            binary_paths: set[str] = set()
            for inst in all_instances:
                if inst.mcc_binary_path:
                    bp = os.path.normpath(inst.mcc_binary_path)
                    binary_paths.add(bp)
                    binary_paths.add(os.path.basename(bp))

            def _match(cmdline_str: str, proc_name: str) -> bool:
                """Match a process as MCC by cmdline path OR by known name patterns.

                Path match first (exact path or basename); then falls back to
                generic MCC binary names so leftovers are still cleaned up even
                when DB paths are empty, stale, or differ from the live cmdline.
                """
                if binary_paths and any(bp in cmdline_str for bp in binary_paths):
                    return True
                lower = (cmdline_str + " " + proc_name).lower()
                if "minecraftclient" in lower:
                    return "exe" in lower or ".dll" in lower or "mono" in lower
                # Weak fallback: executable whose path contains "mcc"
                return "mcc" in lower and ("exe" in lower or ".dll" in lower)

            for proc in psutil.process_iter(["pid", "name", "cmdline"]):
                try:
                    cmdline = proc.info.get("cmdline") or []
                    cmdline_str = " ".join(cmdline)
                    if not cmdline_str:
                        continue
                    if not _match(cmdline_str, proc.info.get("name") or ""):
                        continue
                    pid = proc.pid
                    if pid not in known_pids:
                        proc.kill()
                        known_pids.add(pid)
                        logger.warning("Force-killed orphaned MCC pid={} cmdline={}", pid, cmdline_str[:200])
                        results.append({"instance_id": "orphan", "status": "killed", "pid": pid, "message": "found via psutil scan"})
                except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                    pass
        except Exception as exc:
            logger.warning("Error during psutil orphan scan: {}", exc)
        finally:
            db.close()

    async def start_instance(self, instance_id: str, extra_env: dict[str, str] | None = None) -> dict:
        lock = self._locks.setdefault(instance_id, asyncio.Lock())
        async with lock:
            if self.is_running(instance_id):
                handle = self._processes[instance_id]
                return {"status": "running", "pid": handle.process.pid, "message": "already running"}

            Session = get_session_factory()
            db = Session()
            try:
                instance = db.query(MccInstanceModel).filter(
                    MccInstanceModel.instance_id == instance_id,
                    MccInstanceModel.deleted_at.is_(None),
                ).first()
                if not instance:
                    raise ValueError("MCC instance not found")

                command = self._get_launch_command(instance)
                binary = Path(command[0]) if command else Path("")
                if not command:
                    raise ValueError("Launch command is empty")
                if len(command) == 1 and not binary.exists():
                    raise FileNotFoundError(f"MCC executable not found: {binary}")
                if len(command) > 1 and "{binary}" not in command[0] and command[0] in {"mono", "dotnet"}:
                    target_binary = Path(command[1])
                    if not target_binary.exists():
                        raise FileNotFoundError(f"MCC executable not found: {target_binary}")

                env = os.environ.copy()
                env[instance.mcp_auth_token_env] = instance.mcp_auth_token_secret or ""
                env["MCC_MCP_PORT"] = str(instance.mcp_port)
                env["MCC_MCP_HOST"] = instance.mcp_host
                env["VMT_INSTANCE_ID"] = instance.instance_id
                if extra_env:
                    env.update({str(k): str(v) for k, v in extra_env.items()})

                await self._append_system_line(instance_id, "Starting MCC process: " + " ".join(command))

                # Windows: use subprocess.Popen with CREATE_NEW_CONSOLE
                # so MCC's classic console mode has a console to interact with.
                # The pipe I/O still works — the console is just there to
                # prevent System.Console.GetBufferInfo() from throwing.
                if os.name == "nt":
                    # Windows: DEVNULL stdin prevents console reader thread from
                    # starting, avoiding the ConsoleBuffer.GetBufferInfo crash.
                    # Commands are sent via MCP HTTP API instead of stdin.
                    process = subprocess.Popen(
                        command,
                        cwd=str(instance.instance_dir),
                        env=env,
                        stdin=subprocess.DEVNULL,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.STDOUT,
                    )
                    logger.info("MCC started on Windows with DEVNULL stdin (pid={})", process.pid)
                else:
                    # Linux: PIPE mode. MCC 26.x detects a TTY and switches to
                    # interactive input-echo mode (garbled "Input:" lines) and
                    # repeatedly drops the connection (~20-30s after login),
                    # so we keep the historical PIPE startup for stability.
                    # Terminal resize is silently ignored for PIPE processes
                    # (resize_terminal guards via getattr).
                    process = await asyncio.create_subprocess_exec(
                        *command,
                        cwd=instance.instance_dir,
                        env=env,
                        stdin=asyncio.subprocess.PIPE,
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.STDOUT,
                    )
                    logger.info("MCC started on Linux with PIPE stdin (pid={})", process.pid)

                instance.status = "running"
                instance.desired_state = "running"
                instance.pid = process.pid
                instance.exit_code = None
                instance.last_started_at = datetime.now(timezone.utc)
                db.add(MccProcessEventModel(
                    instance_id=instance_id,
                    event_type="start",
                    pid=process.pid,
                    message="MCC process started",
                ))
                db.commit()

                # Cancel old tasks if restarting (auto-reconnect)
                old = self._processes.pop(instance_id, None)
                if old:
                    old.output_task.cancel()
                    old.exit_task.cancel()

                output_task = asyncio.create_task(self._read_output_loop(instance_id, process))
                exit_task = asyncio.create_task(self._watch_exit_loop(instance_id, process))
                self._processes[instance_id] = ProcessHandle(
                    instance_id=instance_id,
                    process=process,
                    output_task=output_task,
                    exit_task=exit_task,
                    lock=lock,
                )
                await self._emit_status(instance_id, "running", pid=process.pid, mcp_port=instance.mcp_port)

                # Register bot with BlueMap for server-detected online/offline tracking
                self._register_bot_bluemap(instance)

                # If this is an auto-reconnect, wait for BlueMap to confirm the
                # player actually joined the server, then send "已成功重连"
                mc_username = self._pending_reconnect.pop(instance_id, None)
                if mc_username and instance.mc_username:
                    import asyncio as _asyncio
                    instance_name = instance.display_name or instance.slug
                    _asyncio.ensure_future(
                        self._on_reconnect_started(instance_id, mc_username, instance_name)
                    )

                return {"status": "running", "pid": process.pid, "message": "started"}
            except Exception as exc:
                db.rollback()
                # Clean up pending reconnect on failure
                self._pending_reconnect.pop(instance_id, None)
                instance = db.query(MccInstanceModel).filter(MccInstanceModel.instance_id == instance_id).first()
                if instance:
                    instance.status = "error"
                    instance.desired_state = "stopped"
                    instance.pid = None
                    db.add(MccProcessEventModel(
                        instance_id=instance_id,
                        event_type="error",
                        message=str(exc),
                    ))
                    db.commit()
                    await self._emit_status(instance_id, "error", pid=None, mcp_port=instance.mcp_port, message=str(exc))
                await self._append_system_line(instance_id, f"Failed to start MCC: {exc}")
                raise
            finally:
                db.close()

    async def stop_instance(self, instance_id: str, force: bool = False, timeout_seconds: float = 10.0,
                            preserve_desired_state: bool = False) -> dict:
        """Stop an instance. ``preserve_desired_state=True``（shutdown 场景）只停进程、
        不改 desired_state，重启后 running 实例自动恢复。"""
        lock = self._locks.setdefault(instance_id, asyncio.Lock())
        async with lock:
            handle = self._processes.get(instance_id)
            # 先取消退出监控任务，避免其检测到进程退出后按 desired_state+auto_reconnect
            # 触发自动重连（shutdown/主动停止时会造成竞争：重连的 start_instance 失败
            # 会把 desired_state 改回 stopped，导致"服务重启后实例不自动恢复"）。
            if handle and handle.exit_task:
                handle.exit_task.cancel()
                try:
                    await handle.exit_task
                except asyncio.CancelledError:
                    pass
                handle.exit_task = None
            Session = get_session_factory()
            db = Session()
            try:
                instance = db.query(MccInstanceModel).filter(MccInstanceModel.instance_id == instance_id).first()
                if instance:
                    instance.status = "stopping"
                    if not preserve_desired_state:
                        instance.desired_state = "stopped"
                    db.commit()
                    await self._emit_status(instance_id, "stopping", pid=instance.pid, mcp_port=instance.mcp_port)

                if not handle or handle.process.returncode is not None:
                    if instance:
                        instance.status = "stopped"
                        instance.pid = None
                        instance.last_stopped_at = datetime.now(timezone.utc)
                        db.add(MccProcessEventModel(instance_id=instance_id, event_type="stop", message="Already stopped"))
                        db.commit()
                        await self._emit_status(instance_id, "stopped", pid=None, mcp_port=instance.mcp_port)
                    self._processes.pop(instance_id, None)
                    return {"status": "stopped", "pid": None, "message": "already stopped"}

                await self._append_system_line(instance_id, "Stopping MCC process")
                if force:
                    # Fast path: SIGKILL/TerminateProcess immediately, then
                    # wait briefly. Do NOT sit idle waiting for a graceful
                    # exit — that stalls "kill all" past HTTP client timeouts.
                    try:
                        handle.process.kill()
                    except Exception:
                        pass
                    try:
                        if _is_async_proc(handle.process):
                            await asyncio.wait_for(handle.process.wait(), timeout=timeout_seconds)
                        else:
                            loop = asyncio.get_event_loop()
                            await asyncio.wait_for(loop.run_in_executor(None, handle.process.wait), timeout=timeout_seconds)
                    except asyncio.TimeoutError:
                        logger.warning("Force-kill instance {} pid={} did not exit within {}s, retrying", instance_id, handle.process.pid, timeout_seconds)
                        try:
                            handle.process.kill()
                        except Exception:
                            pass
                        try:
                            if _is_async_proc(handle.process):
                                await asyncio.wait_for(handle.process.wait(), timeout=2)
                            else:
                                loop = asyncio.get_event_loop()
                                await asyncio.wait_for(loop.run_in_executor(None, handle.process.wait), timeout=2)
                        except asyncio.TimeoutError:
                            logger.warning("Force-kill instance {} pid={} still alive after retry (left for psutil sweep)", instance_id, handle.process.pid)
                else:
                    try:
                        handle.process.terminate()
                    except Exception:
                        pass
                    try:
                        if _is_async_proc(handle.process):
                            await asyncio.wait_for(handle.process.wait(), timeout=timeout_seconds)
                        else:
                            loop = asyncio.get_event_loop()
                            await asyncio.wait_for(loop.run_in_executor(None, handle.process.wait), timeout=timeout_seconds)
                    except asyncio.TimeoutError:
                        # 优雅停止超时 → 直接强杀，绝不再无限等待
                        logger.warning("Graceful stop timed out for instance {} pid={}, force killing", instance_id, handle.process.pid)
                        try:
                            handle.process.kill()
                        except Exception:
                            pass
                        try:
                            if _is_async_proc(handle.process):
                                await asyncio.wait_for(handle.process.wait(), timeout=3)
                            else:
                                loop = asyncio.get_event_loop()
                                await asyncio.wait_for(loop.run_in_executor(None, handle.process.wait), timeout=3)
                        except asyncio.TimeoutError:
                            logger.warning("Force-kill wait timed out for instance {} pid={} (left for psutil sweep)", instance_id, handle.process.pid)

                returncode = handle.process.returncode
                if instance:
                    # Graceful exit → stopped; force-kill is user-requested → stopped;
                    # anything else (unexpected exit) → crashed.
                    stopped_gracefully = (returncode == 0) or force
                    instance.status = "stopped" if stopped_gracefully else "crashed"
                    instance.pid = None
                    instance.exit_code = returncode
                    instance.last_stopped_at = datetime.now(timezone.utc)
                    db.add(MccProcessEventModel(
                        instance_id=instance_id,
                        event_type="stop" if stopped_gracefully else "crash",
                        exit_code=returncode,
                        message="MCC process stopped",
                    ))
                    db.commit()
                    await self._emit_status(instance_id, instance.status, pid=None, mcp_port=instance.mcp_port)
                # 同步关联 Bot 为离线（前端立即隐藏血量/坐标）
                if instance and instance.bot_id:
                    await self._sync_bot_offline(instance.bot_id)
                self._processes.pop(instance_id, None)
                return {"status": instance.status if instance else "stopped", "pid": None, "message": "stopped"}
            finally:
                db.close()

    # Safe MCC internal commands (won't be sent as in-game chat)
    _SAFE_COMMANDS: set[str] = {
        "help", "status", "quit", "exit", "reco", "connect",
        "disconnect", "respawn", "login", "logout", "reconnect",
        "inventory", "move", "list",
    }

    async def write_stdin(
        self,
        instance_id: str,
        text: str,
        append_newline: bool = True,
        source_sid: str | None = None,
    ) -> None:
        """Write a line to the MCC process stdin.

        `source_sid` is the socket id that submitted the input; it is echoed in
        the broadcast payload so the originating client can skip re-rendering
        its own locally-echoed input line.
        """
        handle = self._processes.get(instance_id)
        if not handle or handle.process.returncode is not None:
            raise RuntimeError("MCC process is not running")

        command = text.strip()
        first_word = command.split()[0].lower() if command else ""

        # 统一路由（命令/聊天合二为一，无需手动输入 say）：
        #   /xxx        → 服务器命令（原样发送）
        #   say xxx     → 游戏聊天（剔除 say 前缀后发送）
        #   MCC 内部命令 → 内部命令（原样发送）
        #   其他文本    → 自动作为游戏聊天发送（自动补 say）
        if command and not command.startswith("/") and not command.startswith("say ") and first_word not in self._SAFE_COMMANDS:
            command = f"say {command}"

        if handle.process.stdin:
            # Linux: stdin 可用，MCC 会把未识别的行当作游戏聊天发出，
            # 因此必须剔除 "say " 前缀，否则游戏聊天栏会显示 "say xxx" 而不是 "xxx"。
            payload_text = command[4:].strip() if command.lower().startswith("say ") else command
            payload = payload_text + ("\n" if append_newline else "")
            proc = handle.process
            if _is_async_proc(proc):
                proc.stdin.write(payload.encode("utf-8"))
                await proc.stdin.drain()
            else:
                loop = asyncio.get_event_loop()
                await loop.run_in_executor(None, proc.stdin.write, payload.encode("utf-8"))
                await loop.run_in_executor(None, proc.stdin.flush)
        else:
            # Windows: stdin 为 DEVNULL，走 MCP HTTP API
            await self._send_via_mcp(instance_id, command)

        await self._append_line(instance_id, "stdin", f"> {text}", from_sid=source_sid)

    async def resize_terminal(self, instance_id: str, cols: int, rows: int) -> None:
        """Resize the terminal of a running instance.

        Current Linux/Windows startup uses PIPE/DEVNULL processes without a
        PTY, so this is a no-op (kept for forward-compatibility with a future
        PTY-based launch; validated bounds and process checks still apply).
        """
        if not (1 <= int(cols) <= 500 and 1 <= int(rows) <= 200):
            raise ValueError("Invalid terminal size")
        handle = self._processes.get(instance_id)
        if not handle or handle.process.returncode is not None:
            raise RuntimeError("MCC process is not running")
        resize = getattr(handle.process, "resize", None)
        if resize is None:
            # PIPE/DEVNULL-based processes have no PTY to resize.
            return
        resize(int(cols), int(rows))
        logger.info("Resized terminal for instance {} to {}x{}", instance_id, cols, rows)

    async def _send_via_mcp(self, instance_id: str, command: str) -> None:
        """Send an MCC command via MCP HTTP API. Handles chat vs internal command routing."""
        Session = get_session_factory()
        db = Session()
        try:
            instance = db.query(MccInstanceModel).filter(
                MccInstanceModel.instance_id == instance_id,
                MccInstanceModel.deleted_at.is_(None),
            ).first()
            if not instance:
                raise RuntimeError("MCC instance not found")

            client = MccMcpClient(
                host=instance.mcp_host,
                port=instance.mcp_port,
                auth_token=instance.mcp_auth_token_secret or None,
            )
            connected = await client.connect()
            if not connected:
                raise RuntimeError("MCC MCP not reachable")

            # Route: "say xxx" → SendChat; everything else → RunInternalCommand
            if command.lower().startswith("say "):
                chat_text = command[4:].strip()
                logger.info("Sending chat via MCP for {}: {}", instance_id, chat_text)
                result = await client.send_chat(chat_text)
            else:
                logger.info("Sending command via MCP for {}: {}", instance_id, command)
                result = await client.run_internal_command(command)
                # If command not recognized, fall back to sending as chat
                if isinstance(result, dict) and not result.get("success", True):
                    logger.info("Command not recognized, falling back to SendChat for {}: {}", instance_id, command)
                    result = await client.send_chat(command)

            logger.info("MCP command result for {}: {}", instance_id, result)
            await client.disconnect()
        except Exception as exc:
            logger.error("MCP command failed for {}: {}", instance_id, exc)
            raise RuntimeError(f"Failed to send command via MCP: {exc}") from exc
        finally:
            db.close()

    async def _send_via_mcp_raw(self, instance: MccInstanceModel, command: str) -> None:
        """Fallback raw HTTP call for older MCC versions that don't need full handshake."""
        import httpx
        url = f"http://{instance.mcp_host}:{instance.mcp_port}/mcp"
        headers = {"Content-Type": "application/json"}
        if instance.mcp_auth_token_secret:
            headers["Authorization"] = f"Bearer {instance.mcp_auth_token_secret}"

        for tool_name in ("mcc_run_internal_command", "RunInternalCommand"):
            payload = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {"name": tool_name, "arguments": {"command": command}},
            }
            async with httpx.AsyncClient(timeout=httpx.Timeout(10.0)) as client:
                resp = await client.post(url, json=payload, headers=headers)
                if resp.status_code >= 500:
                    continue
                if resp.status_code == 200:
                    logger.info("Raw MCP command sent with tool {}: {} -> {}", tool_name, command, resp.text[:200])
                    return
                if resp.status_code >= 400 and "tool" not in resp.text.lower() and "not found" not in resp.text.lower():
                    raise RuntimeError(f"MCP command failed: HTTP {resp.status_code} {resp.text[:200]}")

        raise RuntimeError("MCP RunInternalCommand not available")

    def tail_logs(self, instance_id: str, tail: int = 500, after_seq: int | None = None) -> list[TerminalLine]:
        """Return the most recent terminal lines.

        The in-memory ring buffer is authoritative for recent lines; when the
        buffer holds fewer than `tail` lines (e.g. right after a backend restart
        or when the ring dropped older entries), older history is filled in from
        the DB and merged by sequence number.
        """
        buf_lines = self.buffer.tail(instance_id, tail, after_seq)
        if after_seq is not None:
            buf_lines = [line for line in buf_lines if line.seq > after_seq]

        # Buffer alone is sufficient only if it already covers the whole window.
        if len(buf_lines) >= tail:
            return buf_lines[-max(0, tail):]

        Session = get_session_factory()
        db = Session()
        try:
            query = db.query(MccTerminalLogModel).filter(MccTerminalLogModel.instance_id == instance_id)
            if after_seq is not None:
                query = query.filter(MccTerminalLogModel.seq > after_seq)
            covered = {line.seq for line in buf_lines}
            if covered:
                query = query.filter(MccTerminalLogModel.seq.notin_(covered))
            rows = query.order_by(MccTerminalLogModel.seq.desc()).limit(tail).all()
            rows.reverse()
            for row in rows:
                self.buffer.sync_seq(instance_id, row.seq)
            db_rows = [
                TerminalLine(
                    instance_id=row.instance_id,
                    seq=row.seq,
                    stream=row.stream,
                    content=row.content_masked or row.content,
                    created_at=row.created_at,
                )
                for row in rows
            ]
        finally:
            db.close()

        merged = sorted(db_rows + buf_lines, key=lambda line: line.seq)
        return merged[-max(0, tail):]

    @staticmethod
    def _sanitize_ansi(line: str) -> str:
        """Strip ANSI sequences that would corrupt line-by-line terminal rendering.

        Keeps SGR color/style sequences (ending in ``m``) so xterm still renders
        colors, but removes clear-screen, cursor-move, cursor-visibility and
        other CSI sequences that assume a full-screen raw terminal.
        """
        import re

        def _repl(match: "re.Match[str]") -> str:
            seq = match.group(0)
            return seq if seq.endswith("m") else ""

        return re.sub(r"\x1b\[[0-9;?]*[A-Za-z]", _repl, line)

    async def _read_output_loop(self, instance_id: str, process: "asyncio.subprocess.Process | subprocess.Popen") -> None:
        """Read process stdout line by line."""
        if process.stdout is None:
            return
        loop = asyncio.get_event_loop()
        while True:
            raw: bytes | None
            if _is_async_proc(process):
                raw = await process.stdout.readline()
            else:
                raw = await loop.run_in_executor(None, process.stdout.readline)
            if not raw:
                break
            content = raw.decode("utf-8", errors="replace").rstrip("\r\n")
            content = self._sanitize_ansi(content)
            if content:
                try:
                    await self._append_line(instance_id, "stdout", content)
                except Exception:
                    pass

    async def _watch_exit_loop(self, instance_id: str, process: asyncio.subprocess.Process | subprocess.Popen) -> None:
        if _is_async_proc(process):
            returncode = await process.wait()
        else:
            loop = asyncio.get_event_loop()
            returncode = await loop.run_in_executor(None, process.wait)
        Session = get_session_factory()
        db = Session()
        try:
            instance = db.query(MccInstanceModel).filter(MccInstanceModel.instance_id == instance_id).first()
            if not instance:
                return
            if instance.status not in ("stopping", "stopped", "crashed"):
                instance.status = "stopped" if returncode == 0 else "crashed"
            instance.pid = None
            instance.exit_code = returncode
            instance.last_stopped_at = datetime.now(timezone.utc)
            db.add(MccProcessEventModel(
                instance_id=instance_id,
                event_type="exit" if returncode == 0 else "crash",
                exit_code=returncode,
                message=f"MCC process exited with code {returncode}",
            ))
            db.commit()

            # Auto-reconnect: if enabled and crashed, restart.
            # Skip if _check_auto_reconnect already handled it (detected via terminal).
            should_reconnect = (
                instance.auto_reconnect
                and instance.status == "crashed"
                and instance.desired_state == "running"
                and instance_id not in self._pending_reconnect
            )
            if should_reconnect:
                db.refresh(instance)
                logger.info("Auto-reconnect: restarting crashed instance {}", instance_id)
                await self._append_system_line(instance_id, "Auto-reconnect: restarting...")
                # Send QQ notification
                try:
                    from vmtools_next.core.qqbot_notify import notify_reconnect_started
                    name = instance.display_name or instance.slug
                    import asyncio as _asyncio2
                    _asyncio2.ensure_future(notify_reconnect_started(name))
                except Exception:
                    pass
                # Mark for reconnect-success tracking
                self._pending_reconnect[instance_id] = instance.mc_username
                # Reset status for restart
                instance.status = "created"
                instance.pid = None
                db.commit()

            await self._append_system_line(instance_id, f"MCC exited with code {returncode}")
            await self._emit_status(instance_id, instance.status, pid=None, mcp_port=instance.mcp_port)

            # 同步关联 Bot 为离线（前端血量/坐标随之隐藏；自动重连场景跳过避免闪烁）
            if instance and instance.bot_id and not should_reconnect:
                await self._sync_bot_offline(instance.bot_id)

            # Trigger actual restart in background
            if should_reconnect:
                try:
                    import asyncio as _asyncio3
                    _asyncio3.ensure_future(self.start_instance(instance_id))
                except Exception:
                    pass
        finally:
            db.close()
            # Only pop if our process is still the stored one (may have been
            # replaced by auto-reconnect in _check_auto_reconnect)
            current = self._processes.get(instance_id)
            if current is not None and current.process is process:
                self._processes.pop(instance_id, None)
            # Stop serialized detection loop and flush any queued DB writes.
            self._stop_detection_loop(instance_id)
            try:
                await self._flush_db_now(instance_id)
            except Exception:
                pass

    async def _append_system_line(self, instance_id: str, content: str) -> TerminalLine:
        return await self._append_line(instance_id, "system", content)

    async def _sync_bot_offline(self, bot_id: str) -> None:
        """同步 Bot 为离线状态（写库 + Socket.IO 推送）。"""
        from vmtools_next.data.models.logistics import MccBotModel

        Session = get_session_factory()
        db = Session()
        try:
            bot = db.query(MccBotModel).filter(MccBotModel.bot_id == bot_id).first()
            if bot and bot.status != "offline":
                bot.status = "offline"
                db.commit()
        except Exception as exc:
            logger.warning("Sync bot offline failed for %s: %s", bot_id, exc)
        finally:
            db.close()
        try:
            await sio.emit("bot_status_update", {"bot_id": bot_id, "status": "offline"})
        except Exception as exc:
            logger.warning("Emit bot offline failed for %s: %s", bot_id, exc)

    def _ensure_detection_loop(self, instance_id: str) -> None:
        """Start (once) the per-instance serialized stdout detection consumer."""
        if instance_id in self._detection_tasks:
            return
        queue: asyncio.Queue[str] = asyncio.Queue()
        self._detection_queues[instance_id] = queue
        self._detection_tasks[instance_id] = asyncio.create_task(
            self._detection_loop(instance_id, queue)
        )

    def _stop_detection_loop(self, instance_id: str) -> None:
        task = self._detection_tasks.pop(instance_id, None)
        self._detection_queues.pop(instance_id, None)
        if task and not task.done():
            task.cancel()

    async def _detection_loop(self, instance_id: str, queue: asyncio.Queue[str]) -> None:
        """Consume stdout lines strictly in order and run event detection."""
        try:
            while True:
                content = await queue.get()
                try:
                    await self._detect_disconnect(instance_id, content)
                    # Player join/leave detection via terminal is disabled when BlueMap is active
                    if not get_config().bluemap.enabled:
                        await self._detect_player_events(instance_id, content)
                except Exception:
                    pass
                finally:
                    queue.task_done()
        except asyncio.CancelledError:
            pass

    def _queue_db_write(self, instance_id: str, stream: str, raw_content: str, line: TerminalLine) -> None:
        """Queue a terminal line for batched DB persistence."""
        self._pending_db.setdefault(instance_id, []).append(
            MccTerminalLogModel(
                instance_id=instance_id,
                stream=stream,
                seq=line.seq,
                content=raw_content,
                content_masked=line.content,
                created_at=line.created_at,
            )
        )
        task = self._db_flush_tasks.get(instance_id)
        if task is None or task.done():
            self._db_flush_tasks[instance_id] = asyncio.create_task(
                self._flush_db_loop(instance_id)
            )

    async def _flush_db_loop(self, instance_id: str) -> None:
        """Periodically flush queued terminal lines for an instance."""
        try:
            while True:
                await asyncio.sleep(0.5)
                rows = self._pending_db.get(instance_id)
                if not rows:
                    # Double-sleep so lines that arrived during the first wait
                    # still get flushed before the task exits.
                    await asyncio.sleep(0.5)
                    rows = self._pending_db.get(instance_id)
                    if not rows:
                        return
                self._pending_db[instance_id] = []
                await self._persist_rows(instance_id, rows)
        except asyncio.CancelledError:
            pass

    async def _flush_db_now(self, instance_id: str) -> None:
        """Immediately persist all queued lines (used on process exit)."""
        # Stop the background flush loop first so it cannot double-write the
        # same batch we are about to take.
        task = self._db_flush_tasks.pop(instance_id, None)
        if task and not task.done():
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass
        rows = self._pending_db.pop(instance_id, [])
        if rows:
            await self._persist_rows(instance_id, rows)

    async def _persist_rows(self, instance_id: str, rows: list) -> None:
        Session = get_session_factory()
        db = Session()
        try:
            db.add_all(rows)
            db.commit()
        except Exception as exc:
            db.rollback()
            logger.debug("Failed to persist {} MCC terminal lines: {}", len(rows), exc)
        finally:
            db.close()

    async def _append_line(
        self,
        instance_id: str,
        stream: str,
        content: str,
        from_sid: str | None = None,
    ) -> TerminalLine:
        masked = mask_text(content)
        line = self.buffer.append(instance_id, stream, masked)

        # Batched DB persistence (non-blocking for the read loop).
        self._queue_db_write(instance_id, stream, content, line)

        # Serialized stdout event detection: enqueue strictly in order.
        if stream == "stdout":
            self._ensure_detection_loop(instance_id)
            self._detection_queues[instance_id].put_nowait(content)

        await sio.emit("mcc_terminal_output", {
            "instance_id": instance_id,
            "seq": line.seq,
            "stream": stream,
            "content": masked,
            "from_sid": from_sid,
            "created_at": line.created_at.isoformat(),
        }, room=f"mcc:{instance_id}")
        return line

    # ── BlueMap bot tracking helpers ──────────────────────────────────

    @staticmethod
    def _register_bot_bluemap(instance: MccInstanceModel) -> None:
        """Register the instance's mc_username with BlueMap for join/leave tracking."""
        if not instance.mc_username:
            return
        from vmtools_next.core.bluemap_monitor import register_bot_player
        name = instance.display_name or instance.slug
        register_bot_player(instance.mc_username, name)

    @staticmethod
    def _unregister_bot_bluemap(instance: MccInstanceModel) -> None:
        """Unregister the instance's mc_username from BlueMap tracking."""
        if not instance.mc_username:
            return
        from vmtools_next.core.bluemap_monitor import unregister_bot_player
        unregister_bot_player(instance.mc_username)

    async def _unregister_bot_instance(self, instance_id: str) -> None:
        """Look up instance and unregister its bot from BlueMap tracking."""
        Session = get_session_factory()
        db = Session()
        try:
            inst = db.query(MccInstanceModel).filter(
                MccInstanceModel.instance_id == instance_id
            ).first()
            if inst:
                self._unregister_bot_bluemap(inst)
        finally:
            db.close()

    async def _on_reconnect_started(
        self, instance_id: str, mc_username: str, instance_name: str
    ) -> None:
        """Wait for BlueMap to confirm the player joined, then send success notification."""
        online = await self._wait_for_player_online(mc_username)
        if online:
            # Suppress the normal "上线了喵" from BlueMap since we send "已成功重连"
            from vmtools_next.core.bluemap_monitor import suppress_next_join
            suppress_next_join(mc_username)

            try:
                from vmtools_next.core.qqbot_notify import notify_reconnect_success
                await notify_reconnect_success(instance_name)
            except Exception:
                pass
            await self._append_system_line(instance_id, "自动重连成功（BlueMap 确认在线）")
        else:
            await self._append_system_line(
                instance_id, f"自动重连可能失败（{int(self._wait_for_player_online.__defaults__[0])}s 内未检测到在线）"
            )
            logger.warning(
                "Auto-reconnect: player {} not detected online for instance {}", mc_username, instance_name
            )

    async def _wait_for_player_online(
        self, mc_username: str, timeout: float = 120.0
    ) -> bool:
        """Poll BlueMap API until a specific player appears online.

        Returns True if the player was detected online, False on timeout.
        """
        cfg = get_config()
        if not cfg.bluemap.enabled:
            return False

        import time as _time
        import httpx as _httpx

        start = _time.monotonic()
        while _time.monotonic() - start < timeout:
            try:
                async with _httpx.AsyncClient(timeout=_httpx.Timeout(10.0)) as client:
                    for world in cfg.bluemap.worlds:
                        url = f"{cfg.bluemap.api_base_url}/maps/{world}/live/players.json"
                        resp = await client.get(url)
                        if resp.status_code != 200:
                            continue
                        data = resp.json()
                        for p in data.get("players", []):
                            if p.get("foreign", False):
                                continue
                            if p.get("name") == mc_username:
                                logger.info(
                                    "Auto-reconnect: player {} detected online via BlueMap", mc_username
                                )
                                return True
            except Exception as exc:
                logger.debug("BlueMap poll (reconnect wait) error: {}", exc)
            await asyncio.sleep(5)
        logger.warning("Auto-reconnect: player {} not detected online within {:.0f}s", mc_username, timeout)
        return False

    # ── Disconnect detection patterns (from MCC source) ──────────────

    async def _check_auto_reconnect(self, instance_id: str) -> None:
        """Trigger auto-reconnect if enabled for this instance."""
        import asyncio as _asyncio
        Session = get_session_factory()
        db2 = Session()
        try:
            inst = db2.query(MccInstanceModel).filter(
                MccInstanceModel.instance_id == instance_id
            ).first()
            if inst and inst.auto_reconnect and inst.desired_state == "running":
                logger.info("Auto-reconnect triggered by disconnect: {}", instance_id)
                await self._append_system_line(instance_id, "检测到断联，自动重连...")

                # Send QQ notification: auto-reconnect started
                try:
                    from vmtools_next.core.qqbot_notify import notify_reconnect_started
                    name = inst.display_name or inst.slug
                    _asyncio.ensure_future(notify_reconnect_started(name))
                except Exception:
                    pass

                # Mark for reconnect-success tracking in _watch_exit_loop
                self._pending_reconnect[instance_id] = inst.mc_username

                # Kill the old process if it's still lingering
                old = self._processes.get(instance_id)
                if old:
                    try:
                        old.process.kill()
                    except Exception:
                        pass
                    old.output_task.cancel()
                    old.exit_task.cancel()
                    self._processes.pop(instance_id, None)

                # Reset status so start_instance allows re-launch
                inst.status = "stopped"
                inst.pid = None
                db2.commit()

                _asyncio.ensure_future(self.start_instance(instance_id))
        finally:
            db2.close()
    _DISCONNECT_PATTERNS: list[tuple[str, str]] = [
        # (pattern, category)
        ("Disconnected by Server", "kicked"),
        ("Connection has been lost", "connection_lost"),
        ("Connection Timeout", "timeout"),
        ("Login failed", "login_rejected"),
        ("Failed to connect to this IP", "connect_failed"),
        ("timeout occured while attempting to connect", "connect_timeout"),
        ("Got disconnected with message", "kicked"),
        ("Forge Login Handshake did not complete", "forge_error"),
        ("Server does not report its protocol version", "protocol_error"),
        ("Invalid response to StartEncryption", "encrypt_error"),
    ]

    async def _detect_disconnect(self, instance_id: str, content: str) -> None:
        """Check terminal output for known MCC disconnect patterns and trigger alerts."""
        # If we have a pending disconnect, this line is the kick reason.
        # Use get() + non-empty check so a stray blank line does not consume
        # the pending marker before the real reason line arrives.
        pending = self._pending_disconnect.get(instance_id)
        if pending:
            if not content.strip():
                return
            self._pending_disconnect.pop(instance_id, None)
            import asyncio as _asyncio
            from vmtools_next.core.qqbot_notify import notify_mcc_event
            try:
                name = await self._get_instance_name(instance_id)
                reason = content.strip()
                # Strip ANSI color codes
                import re
                reason = re.sub(r"\x1b\[[0-9;]*m", "", reason)
                reason = re.sub(r"\d{1,2}:\d{2}:\d{2}\s*\[.*?\]\s*", "", reason).strip()
                if reason:
                    msg = f"因为「{reason[:100]}」似了喵"
                else:
                    msg = "似了喵（原因未知）"
                _asyncio.ensure_future(notify_mcc_event(name, "crashed", msg))
                # Unregister from BlueMap to prevent duplicate "下线了喵"
                await self._unregister_bot_instance(instance_id)
                await self._check_auto_reconnect(instance_id)
            except Exception:
                pass
            return

        for pattern, category in self._DISCONNECT_PATTERNS:
            if pattern.lower() in content.lower():
                logger.warning("MCC disconnect detected: instance={} category={} pattern={}",
                               instance_id, category, pattern)
                if category == "kicked":
                    # Wait for next line to get the real kick reason
                    self._pending_disconnect[instance_id] = content
                elif category == "login_rejected":
                    # Temporary IP rate-limit — MCC AutoRelog handles it.
                    pass
                else:
                    labels = {
                        "connection_lost": "连接丢失",
                        "timeout": "连接超时",
                        "login_rejected": "登录被拒",
                        "connect_failed": "连接失败",
                        "connect_timeout": "连接超时",
                        "forge_error": "Forge 握手失败",
                        "protocol_error": "协议错误",
                        "encrypt_error": "加密错误",
                    }
                    label = labels.get(category, category)
                    import asyncio as _asyncio
                    from vmtools_next.core.qqbot_notify import notify_mcc_event
                    try:
                        name = await self._get_instance_name(instance_id)
                        _asyncio.ensure_future(
                            notify_mcc_event(name, "crashed", f"因为「{label}」似了喵")
                        )
                    except Exception:
                        pass
                    # Unregister from BlueMap to prevent duplicate "下线了喵"
                    await self._unregister_bot_instance(instance_id)
                    await self._check_auto_reconnect(instance_id)
                break

    # ── Player join/leave detection (for sentinel bots) ──────────────
    _PLAYER_EVENT_PATTERNS: list[tuple[str, str]] = [
        # (regex pattern, event type)
        (r"(\w+) left the game", "leave"),
        (r"(\w+) joined the game", "join"),
        (r"(\S+) 离开了游戏", "leave"),
        (r"(\S+) 加入了游戏", "join"),
        (r"▌?(\w+?)离开了服务器", "leave"),    # 芒果服中文格式
        (r"▌?(\w+?)加入了服务器", "join"),
    ]

    async def _detect_player_events(self, instance_id: str, content: str) -> None:
        """Detect player join/leave from terminal output and notify QQ."""
        from vmtools_next.config import get_config
        cfg = get_config().player_tracking
        if not cfg.enabled or not cfg.sentinel_instance:
            return

        # Lazy cache sentinel instance_id
        if self._sentinel_id is None:
            Session = get_session_factory()
            db = Session()
            try:
                sentinel = db.query(MccInstanceModel).filter(
                    MccInstanceModel.slug == cfg.sentinel_instance
                ).first()
                self._sentinel_id = sentinel.instance_id if sentinel else ""
                logger.warning("Sentinel cached: slug={} -> instance_id={}",
                               cfg.sentinel_instance, self._sentinel_id)
            finally:
                db.close()

        if instance_id != self._sentinel_id:
            return

        import re
        import asyncio as _asyncio
        from vmtools_next.core.qqbot_notify import broadcast

        # Build lookup: player_name → qq_openid from all owners
        tracked: dict[str, str] = {}
        for owner in cfg.owners:
            for pname in owner.track_players:
                tracked[pname] = owner.qq_openid
        logger.warning("Tracked players: {}", tracked)

        for pattern, event_type in self._PLAYER_EVENT_PATTERNS:
            m = re.search(pattern, content)
            if m:
                player = m.group(1)
                logger.warning("Player event: matched={} player={} type={} tracked={}",
                               pattern, player, event_type, player in tracked)
                # Allow partial match: "Venus_Yu002" should match "93mVenus_Yu002"
                qq: str | None = None
                display = player
                if player in tracked:
                    qq = tracked[player]
                else:
                    for tname, tqq in tracked.items():
                        if tname in player:
                            qq = tqq
                            display = tname  # use clean config name
                            break
                if not qq:
                    continue
                label = "离线了喵" if event_type == "leave" else "上线了喵"
                msg = f"{display} {label}"
                logger.info("Tracked player event: {} {} -> QQ {}", player, event_type, qq)
                _asyncio.ensure_future(broadcast(msg, mention_openids=[qq] if qq else None))
                break

    async def _get_instance_name(self, instance_id: str) -> str:
        """Get display name or slug for notifications."""
        Session = get_session_factory()
        db = Session()
        try:
            instance = db.query(MccInstanceModel).filter(
                MccInstanceModel.instance_id == instance_id
            ).first()
            if instance:
                return instance.display_name or instance.slug
            return instance_id
        finally:
            db.close()

    async def _emit_status(
        self,
        instance_id: str,
        status: str,
        pid: int | None,
        mcp_port: int,
        message: str = "",
    ) -> None:
        # QQ notifications are now sent by BlueMap monitor when it detects
        # the player actually join/leave the server, not from button clicks.
        # Only Socket.IO emission here for frontend reactivity.
        await sio.emit("mcc_instance_status", {
            "instance_id": instance_id,
            "status": status,
            "pid": pid,
            "mcp_port": mcp_port,
            "message": message,
        }, room=f"mcc:{instance_id}")
        await sio.emit("mcc_instance_status", {
            "instance_id": instance_id,
            "status": status,
            "pid": pid,
            "mcp_port": mcp_port,
            "message": message,
        })

    def _get_launch_command(self, instance: MccInstanceModel) -> list[str]:
        if instance.launch_command_json:
            try:
                value = json.loads(instance.launch_command_json)
                if isinstance(value, list) and all(isinstance(item, str) for item in value):
                    return value
            except json.JSONDecodeError:
                pass
        if self.config.launch_command:
            return [part.replace("{binary}", instance.mcc_binary_path) for part in self.config.launch_command]
        binary = instance.mcc_binary_path
        suffix = Path(binary).suffix.lower()
        if suffix == ".dll":
            return ["dotnet", binary]
        if suffix == ".exe":
            if os.name == "nt":
                return [binary]
            return ["mono", binary]
        return [binary]

    async def _mark_stale_running_instances(self) -> None:
        Session = get_session_factory()
        db = Session()
        try:
            # 只标记 MCC 实例；mineflayer 实例由 MineflayerProcessManager 管理
            for instance in db.query(MccInstanceModel).filter(
                MccInstanceModel.status.in_(["starting", "running", "stopping"]),
                MccInstanceModel.bot_engine != "mineflayer",
            ).all():
                instance.status = "stopped"
                instance.pid = None
                db.add(MccProcessEventModel(
                    instance_id=instance.instance_id,
                    event_type="exit",
                    message="Backend restarted; previous process handle was cleared",
                ))
            db.commit()
        finally:
            db.close()

    async def _recover_desired_running_instances(self) -> None:
        Session = get_session_factory()
        db = Session()
        try:
            # 只恢复 MCC 实例；mineflayer 实例由 MineflayerProcessManager 恢复
            instance_ids = [
                row.instance_id
                for row in db.query(MccInstanceModel).filter(
                    MccInstanceModel.deleted_at.is_(None),
                    MccInstanceModel.desired_state == "running",
                    MccInstanceModel.bot_engine != "mineflayer",
                ).all()
            ]
        finally:
            db.close()

        for instance_id in instance_ids:
            try:
                await self._append_system_line(instance_id, "Recovering MCC instance after backend restart")
                await self.start_instance(instance_id)
            except Exception as exc:
                logger.warning("Failed to recover MCC instance {}: {}", instance_id, exc)
