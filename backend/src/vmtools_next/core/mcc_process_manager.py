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


class MccProcessManager:
    """Manage MCC child processes and stream their terminal output."""

    def __init__(self, buffer: TerminalLogBuffer | None = None):
        self.config = get_config().mcc
        self.buffer = buffer or TerminalLogBuffer()
        self._processes: dict[str, ProcessHandle] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        self._started = False

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
                    # Linux: wrap command in `script` to allocate a PTY.
                    # This makes MCC think it's running in a real terminal and
                    # flushes stdout line-by-line. Without PTY, Mono buffers
                    # all output until the 64KB pipe buffer fills up.
                    import shlex
                    wrapped = ["script", "-q", "-c", shlex.join(command), "/dev/null"]
                    process = await asyncio.create_subprocess_exec(
                        *wrapped,
                        cwd=instance.instance_dir,
                        env=env,
                        stdin=asyncio.subprocess.PIPE,
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.STDOUT,
                    )
                    # No kick-start write: sending raw text to MCC stdin would
                    # cause unrecognized text to be treated as in-game chat.
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
                # Use force stop (SIGTERM) instead of sending "exit" via stdin
                # to avoid MCC sending "exit" as a chat message to the server
                if not force and _is_async_proc(handle.process):
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
        """Read process stdout in chunks and split into lines.

        Using readline() can block on Mono processes because they buffer stdout
        heavily when writing to a PIPE. Reading in fixed-size chunks and splitting
        on newlines is more reliable.
        """
        if process.stdout is None:
            return
        import codecs
        decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
        loop = asyncio.get_event_loop()
        while True:
            chunk: bytes
            if _is_async_proc(process):
                chunk = await process.stdout.read(4096)
            else:
                chunk = await loop.run_in_executor(None, process.stdout.read, 4096)
            if not chunk:
                tail = decoder.decode(b"", final=True)
                if tail:
                    for line in tail.splitlines():
                        if line and not line.startswith("Script "):
                            await self._append_line(instance_id, "stdout", line)
                break
            text = decoder.decode(chunk)
            for line in text.splitlines():
                if line and not line.startswith("Script "):
                    await self._append_line(instance_id, "stdout", line)

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

        # Detect disconnect patterns in MCC output
        if stream == "stdout":
            await self._detect_disconnect(instance_id, content)
            await self._detect_player_events(instance_id, content)

        await sio.emit("mcc_terminal_output", {
            "instance_id": instance_id,
            "seq": line.seq,
            "stream": stream,
            "content": masked,
            "created_at": line.created_at.isoformat(),
        }, room=f"mcc:{instance_id}")
        return line

    # ── Disconnect detection patterns (from MCC source) ──────────────
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
        for pattern, category in self._DISCONNECT_PATTERNS:
            if pattern.lower() in content.lower():
                logger.warning("MCC disconnect detected: instance=%s category=%s pattern=%s",
                               instance_id, category, pattern)
                try:
                    import asyncio as _asyncio
                    from vmtools_next.core.qqbot_notify import notify_mcc_event
                    name = await self._get_instance_name(instance_id)
                    labels = {
                        "kicked": "被服务器踢出",
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
                    _asyncio.ensure_future(
                        notify_mcc_event(name, "crashed", f"🔌 {label}\n{content.strip()[:200]}")
                    )

                    # Auto-reconnect: if enabled, restart the instance
                    Session = get_session_factory()
                    db2 = Session()
                    try:
                        inst = db2.query(MccInstanceModel).filter(
                            MccInstanceModel.instance_id == instance_id
                        ).first()
                        if inst and inst.auto_reconnect and inst.desired_state == "running":
                            logger.info("Auto-reconnect triggered by disconnect: %s", instance_id)
                            await self._append_system_line(instance_id, "检测到断联，自动重连...")
                            _asyncio.ensure_future(self.start_instance(instance_id))
                    finally:
                        db2.close()
                except Exception:
                    pass
                break  # Only trigger once per line

    # ── Player join/leave detection (for sentinel bots) ──────────────
    _PLAYER_EVENT_PATTERNS: list[tuple[str, str]] = [
        # (regex pattern, event type)
        (r"(\w+) left the game", "leave"),
        (r"(\w+) joined the game", "join"),
        (r"(\S+) 离开了游戏", "leave"),
        (r"(\S+) 加入了游戏", "join"),
    ]

    async def _detect_player_events(self, instance_id: str, content: str) -> None:
        """Detect player join/leave from terminal output and notify QQ.

        Only triggers for players configured in player_tracking.players.
        Each tracked player gets a separate @mention with their qq_openid.
        """
        from vmtools_next.config import get_config
        cfg = get_config().player_tracking
        if not cfg.enabled:
            return

        # Only the sentinel instance tracks players
        Session = get_session_factory()
        db = Session()
        try:
            sentinel = db.query(MccInstanceModel).filter(
                MccInstanceModel.slug == cfg.sentinel_instance
            ).first()
            if not sentinel or sentinel.instance_id != instance_id:
                return
        finally:
            db.close()

        import re
        import asyncio as _asyncio
        from vmtools_next.core.qqbot_notify import broadcast

        # Build lookup: player name → qq_openid
        tracked: dict[str, str] = {p.name: p.qq_openid for p in cfg.players}

        for pattern, event_type in self._PLAYER_EVENT_PATTERNS:
            m = re.search(pattern, content)
            if m:
                player = m.group(1)
                if player not in tracked:
                    continue
                emoji = "👋" if event_type == "leave" else "👤"
                label = "离开了服务器" if event_type == "leave" else "加入了服务器"
                msg = f"{emoji} {player} {label}"
                logger.info("Tracked player event: %s %s", player, event_type)
                _asyncio.ensure_future(broadcast(msg))
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
