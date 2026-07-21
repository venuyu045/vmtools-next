"""Async process manager for local/container MCC instances."""
from __future__ import annotations

import asyncio
import json
import os
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
    process: asyncio.subprocess.Process | subprocess.Popen
    output_task: asyncio.Task
    exit_task: asyncio.Task | None = None
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


def _is_async_proc(proc) -> bool:
    """Check if a process object is an asyncio subprocess (has async stdout)."""
    import asyncio as _asyncio
    return hasattr(proc.stdout, "readline") and _asyncio.iscoroutinefunction(proc.stdout.readline)


class _PtyStdout:
    """Async reader wrapper for PTY master fd."""

    def __init__(self, fd: int):
        self._fd = fd

    async def read(self, n: int = 4096) -> bytes:
        loop = asyncio.get_event_loop()
        try:
            return await loop.run_in_executor(None, os.read, self._fd, n)
        except OSError:
            return b""

    async def readline(self) -> bytes:
        loop = asyncio.get_event_loop()
        try:
            return await loop.run_in_executor(None, self._blocking_readline)
        except OSError:
            return b""

    def _blocking_readline(self) -> bytes:
        buf = b""
        while True:
            ch = os.read(self._fd, 1)
            if not ch:
                break
            buf += ch
            if ch == b"\n":
                break
        return buf


class _PtyStdin:
    """Async writer wrapper for PTY master fd."""

    def __init__(self, fd: int):
        self._fd = fd

    def write(self, data: bytes):
        os.write(self._fd, data)

    async def drain(self):
        pass


class PtyProcess:
    """Mimics asyncio.subprocess.Process but backed by a PTY."""

    def __init__(self, master_fd: int, pid: int):
        self._master_fd = master_fd
        self.pid = pid
        self.returncode: int | None = None
        self.stdout = _PtyStdout(master_fd)
        self.stdin = _PtyStdin(master_fd)

    def terminate(self):
        import signal
        try:
            os.kill(self.pid, signal.SIGTERM)
        except OSError:
            pass

    def kill(self):
        import signal
        try:
            os.kill(self.pid, signal.SIGKILL)
        except OSError:
            pass

    async def wait(self, timeout=None):
        import signal
        loop = asyncio.get_event_loop()
        try:
            if timeout:
                pid, status = await asyncio.wait_for(
                    loop.run_in_executor(None, os.waitpid, self.pid, 0),
                    timeout=timeout,
                )
            else:
                pid, status = await loop.run_in_executor(None, os.waitpid, self.pid, 0)
            self.returncode = os.waitstatus_to_exitcode(status)
        except asyncio.TimeoutError:
            os.kill(self.pid, signal.SIGKILL)
            try:
                pid, status = await loop.run_in_executor(None, os.waitpid, self.pid, 0)
                self.returncode = os.waitstatus_to_exitcode(status)
            except (ChildProcessError, ProcessLookupError):
                self.returncode = -9  # killed
        except (ChildProcessError, ProcessLookupError):
            # Process already reaped (e.g. auto-reconnect restarted it)
            self.returncode = self.returncode or 0
        try:
            os.close(self._master_fd)
        except OSError:
            pass
        return self.returncode


class MccProcessManager:
    """Manage MCC child processes and stream their terminal output."""

    def __init__(self, buffer: TerminalLogBuffer | None = None):
        self.config = get_config().mcc
        self.buffer = buffer or TerminalLogBuffer()
        self._processes: dict[str, ProcessHandle] = {}
        self._pending_disconnect: dict[str, str] = {}  # instance_id → disconnect line
        self._locks: dict[str, asyncio.Lock] = {}
        self._started = False
        self._sentinel_id: str | None = None  # cached sentinel instance UUID

    async def start(self) -> None:
        self._started = True
        await self._mark_stale_running_instances()
        await self._recover_desired_running_instances()

    async def stop(self) -> None:
        for instance_id in list(self._processes.keys()):
            try:
                await self.stop_instance(instance_id, force=True, timeout_seconds=2)
            except Exception as exc:
                logger.warning("Failed to stop MCC instance {} during shutdown: {}", instance_id, exc)
        self._started = False

    def is_running(self, instance_id: str) -> bool:
        handle = self._processes.get(instance_id)
        if not handle:
            return False
        proc = handle.process
        return proc.returncode is None

    async def _tail_log(self, instance_id: str, log_path: str) -> None:
        """Tail the MCC output log file and feed lines to the terminal."""
        import time as _time
        # Wait for log file to appear and have content
        waited = 0
        while not os.path.exists(log_path) or os.path.getsize(log_path) == 0:
            if waited > 30:
                logger.warning("Log file %s never appeared", log_path)
                return
            await asyncio.sleep(0.5)
            waited += 0.5

        with open(log_path, "r", encoding="utf-8", errors="replace") as fh:
            fh.seek(0, 2)  # start at end
            while True:
                line = fh.readline()
                if line:
                    line = line.rstrip("\r\n")
                    # Skip script(1) header if present
                    if line and not line.startswith("Script "):
                        try:
                            await self._append_line(instance_id, "stdout", line)
                        except Exception:
                            pass
                else:
                    await asyncio.sleep(0.1)
                    # Check if log file was rotated/deleted
                    if not os.path.exists(log_path):
                        break

    async def _spawn_pty(self, command: list[str], cwd: str, env: dict) -> PtyProcess:
        """Spawn process with PTY for line-buffered output.

        Creates a pseudo-terminal, forks, and execs the command with the
        PTY slave as stdin/stdout/stderr. Echo is disabled to prevent
        input from being reflected back to stdout.

        Also redirects MCC output to a log file for reliable reading.
        """
        import pty
        import termios

        master_fd, slave_fd = pty.openpty()

        # Disable echo only — keep cooked mode so Console.ReadLine() works.
        # Re-enable ONLCR: MCC writes \n, PTY outputs \r\n (normal terminal).
        try:
            attrs = termios.tcgetattr(slave_fd)
            attrs[3] &= ~termios.ECHO   # don't echo input back
            attrs[3] &= ~termios.ECHOE  # don't echo erase
            # Keep ONLCR enabled (default): NL → CR-NL on output
            termios.tcsetattr(slave_fd, termios.TCSANOW, attrs)
        except Exception:
            pass

        pid = os.fork()
        if pid == 0:
            # ── Child process ──
            try:
                os.close(master_fd)
                os.setsid()

                # Set controlling terminal (required for Console.ReadLine on some Mono versions)
                try:
                    import fcntl
                    fcntl.ioctl(slave_fd, termios.TIOCSCTTY, 0)
                except OSError:
                    pass

                # Redirect stdin/stdout/stderr to PTY slave
                os.dup2(slave_fd, 0)
                os.dup2(slave_fd, 1)
                os.dup2(slave_fd, 2)
                if slave_fd > 2:
                    os.close(slave_fd)

                os.chdir(cwd)
                os.execvpe(command[0], command, env)
            except Exception:
                pass
            os._exit(1)  # Must exit if exec fails!
        else:
            # ── Parent process ──
            os.close(slave_fd)
            return PtyProcess(master_fd, pid)

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
                    # Linux: simple asyncio PIPE. readline() handles line
                    # buffering fine — Mono may buffer output on a PIPE,
                    # but the network thread is separate from Console.ReadLine.
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
                return {"status": "running", "pid": process.pid, "message": "started"}
            except Exception as exc:
                db.rollback()
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

    async def stop_instance(self, instance_id: str, force: bool = False, timeout_seconds: float = 10.0) -> dict:
        lock = self._locks.setdefault(instance_id, asyncio.Lock())
        async with lock:
            handle = self._processes.get(instance_id)
            Session = get_session_factory()
            db = Session()
            try:
                instance = db.query(MccInstanceModel).filter(MccInstanceModel.instance_id == instance_id).first()
                if instance:
                    instance.status = "stopping"
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
                if not force:
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
                    handle.process.terminate()
                    try:
                        if _is_async_proc(handle.process):
                            await asyncio.wait_for(handle.process.wait(), timeout=5)
                        else:
                            loop = asyncio.get_event_loop()
                            await asyncio.wait_for(loop.run_in_executor(None, handle.process.wait), timeout=5)
                    except asyncio.TimeoutError:
                        handle.process.kill()
                        if _is_async_proc(handle.process):
                            await handle.process.wait()
                        else:
                            loop = asyncio.get_event_loop()
                            await loop.run_in_executor(None, handle.process.wait)

                returncode = handle.process.returncode
                if instance:
                    # If we sent a graceful exit command, always treat as "stopped"
                    stopped_gracefully = not force and handle.process.stdin is not None
                    instance.status = "stopped" if (returncode == 0 or stopped_gracefully) else "crashed"
                    instance.pid = None
                    instance.exit_code = returncode
                    instance.last_stopped_at = datetime.now(timezone.utc)
                    db.add(MccProcessEventModel(
                        instance_id=instance_id,
                        event_type="stop" if returncode == 0 else "crash",
                        exit_code=returncode,
                        message="MCC process stopped",
                    ))
                    db.commit()
                    await self._emit_status(instance_id, instance.status, pid=None, mcp_port=instance.mcp_port)
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

    async def write_stdin(self, instance_id: str, text: str, append_newline: bool = True) -> None:
        handle = self._processes.get(instance_id)
        if not handle or handle.process.returncode is not None:
            raise RuntimeError("MCC process is not running")

        command = text.strip()
        first_word = command.split()[0].lower() if command else ""

        # Whitelist: MCC sends ANY unrecognized text as in-game chat.
        # Only allow /commands, say chat, or known MCC internal commands.
        if command and not command.startswith("/") and not command.startswith("say ") and first_word not in self._SAFE_COMMANDS:
            raise RuntimeError(
                "拒绝发送: 此文本会被MCC当作游戏聊天发出。请以 / 开头发送指令, 或以 say 开头发送聊天。"
            )

        # If stdin is available (Windows subprocess.Popen), write directly
        if handle.process.stdin:
            payload = text + ("\n" if append_newline else "")
            proc = handle.process
            if _is_async_proc(proc):
                proc.stdin.write(payload.encode("utf-8"))
                await proc.stdin.drain()
            else:
                loop = asyncio.get_event_loop()
                await loop.run_in_executor(None, proc.stdin.write, payload.encode("utf-8"))
                await loop.run_in_executor(None, proc.stdin.flush)
        else:
            # Linux: stdin is DEVNULL, send via MCP HTTP API instead
            await self._send_via_mcp(instance_id, command)

        await self._append_line(instance_id, "stdin", f"> {text}")

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
        lines = self.buffer.tail(instance_id, tail, after_seq)
        if lines:
            return lines
        Session = get_session_factory()
        db = Session()
        try:
            query = db.query(MccTerminalLogModel).filter(MccTerminalLogModel.instance_id == instance_id)
            if after_seq is not None:
                query = query.filter(MccTerminalLogModel.seq > after_seq)
            rows = query.order_by(MccTerminalLogModel.seq.desc()).limit(tail).all()
            rows.reverse()
            for row in rows:
                self.buffer.sync_seq(instance_id, row.seq)
            return [
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

    async def _read_output_loop(self, instance_id: str, process: asyncio.subprocess.Process | subprocess.Popen) -> None:
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

            # Auto-reconnect: if enabled and crashed, restart
            should_reconnect = (
                instance.auto_reconnect
                and instance.status == "crashed"
                and instance.desired_state == "running"
            )
            if should_reconnect:
                db.refresh(instance)
                logger.info("Auto-reconnect: restarting crashed instance %s", instance_id)
                await self._append_system_line(instance_id, "Auto-reconnect: restarting...")
                # Reset status for restart
                instance.status = "created"
                instance.pid = None
                db.commit()

            await self._append_system_line(instance_id, f"MCC exited with code {returncode}")
            await self._emit_status(instance_id, instance.status, pid=None, mcp_port=instance.mcp_port)

            # Trigger actual restart in background
            if should_reconnect:
                try:
                    import asyncio as _asyncio
                    _asyncio.ensure_future(self.start_instance(instance_id))
                except Exception:
                    pass
        finally:
            db.close()
            self._processes.pop(instance_id, None)

    async def _append_system_line(self, instance_id: str, content: str) -> TerminalLine:
        return await self._append_line(instance_id, "system", content)

    async def _append_line(self, instance_id: str, stream: str, content: str) -> TerminalLine:
        masked = mask_text(content)
        line = self.buffer.append(instance_id, stream, masked)
        Session = get_session_factory()
        db = Session()
        try:
            db.add(MccTerminalLogModel(
                instance_id=instance_id,
                stream=stream,
                seq=line.seq,
                content=content,
                content_masked=masked,
                created_at=line.created_at,
            ))
            db.commit()
        except Exception as exc:
            db.rollback()
            logger.debug("Failed to persist MCC terminal line: {}", exc)
        finally:
            db.close()

        # Fire-and-forget: don't block the read loop
        if stream == "stdout":
            asyncio.create_task(self._detect_disconnect(instance_id, content))
            # Player join/leave detection via terminal is disabled when BlueMap is active
            if not get_config().bluemap.enabled:
                asyncio.create_task(self._detect_player_events(instance_id, content))

        await sio.emit("mcc_terminal_output", {
            "instance_id": instance_id,
            "seq": line.seq,
            "stream": stream,
            "content": masked,
            "created_at": line.created_at.isoformat(),
        }, room=f"mcc:{instance_id}")
        return line

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
                logger.info("Auto-reconnect triggered by disconnect: %s", instance_id)
                await self._append_system_line(instance_id, "检测到断联，自动重连...")

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
        # If we have a pending disconnect, this line is the kick reason
        pending = self._pending_disconnect.pop(instance_id, None)
        if pending:
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
                await self._check_auto_reconnect(instance_id)
            except Exception:
                pass
            return

        for pattern, category in self._DISCONNECT_PATTERNS:
            if pattern.lower() in content.lower():
                logger.warning("MCC disconnect detected: instance=%s category=%s pattern=%s",
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
        await sio.emit("mcc_instance_status", {
            "instance_id": instance_id,
            "status": status,
            "pid": pid,
            "mcp_port": mcp_port,
            "message": message,
        }, room=f"mcc:{instance_id}")

        # QQ Bot notification for status changes
        if status in ("running", "stopped", "crashed", "error"):
            try:
                import asyncio as _asyncio
                from vmtools_next.core.qqbot_notify import notify_mcc_event
                name = await self._get_instance_name(instance_id)
                _asyncio.ensure_future(notify_mcc_event(name, status, message))
            except Exception:
                pass
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
            for instance in db.query(MccInstanceModel).filter(MccInstanceModel.status.in_(["starting", "running", "stopping"])).all():
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
            instance_ids = [
                row.instance_id
                for row in db.query(MccInstanceModel).filter(
                    MccInstanceModel.deleted_at.is_(None),
                    MccInstanceModel.desired_state == "running",
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
