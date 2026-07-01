"""Async process manager for local/container MCC instances."""
from __future__ import annotations

import asyncio
import json
import os
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

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
    return hasattr(proc.stdout, "readline") and hasattr(proc.stdout.readline, "__await__")


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
                    process = await asyncio.create_subprocess_exec(
                        *command,
                        cwd=instance.instance_dir,
                        env=env,
                        stdin=asyncio.subprocess.PIPE,
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.STDOUT,
                    )

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
                if not force and handle.process.stdin:
                    try:
                        if _is_async_proc(handle.process):
                            handle.process.stdin.write(b"exit\n")
                            await handle.process.stdin.drain()
                        else:
                            loop = asyncio.get_event_loop()
                            await loop.run_in_executor(None, handle.process.stdin.write, b"exit\n")
                            await loop.run_in_executor(None, handle.process.stdin.flush)
                    except Exception as exc:
                        logger.debug("Failed to write graceful stop command: {}", exc)

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
                    instance.status = "stopped" if returncode == 0 else "crashed"
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

    async def write_stdin(self, instance_id: str, text: str, append_newline: bool = True) -> None:
        handle = self._processes.get(instance_id)
        if not handle or handle.process.returncode is not None or not handle.process.stdin:
            raise RuntimeError("MCC process is not running")
        payload = text + ("\n" if append_newline else "")
        proc = handle.process
        if _is_async_proc(proc):
            proc.stdin.write(payload.encode("utf-8"))
            await proc.stdin.drain()
        else:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, proc.stdin.write, payload.encode("utf-8"))
            await loop.run_in_executor(None, proc.stdin.flush)
        await self._append_line(instance_id, "stdin", f"> {text}")

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
            await self._append_line(instance_id, "stdout", content)

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
            if instance.status != "stopping":
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
            await self._append_system_line(instance_id, f"MCC exited with code {returncode}")
            await self._emit_status(instance_id, instance.status, pid=None, mcp_port=instance.mcp_port)
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
        await sio.emit("mcc_terminal_output", {
            "instance_id": instance_id,
            "seq": line.seq,
            "stream": stream,
            "content": masked,
            "created_at": line.created_at.isoformat(),
        }, room=f"mcc:{instance_id}")
        return line

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
