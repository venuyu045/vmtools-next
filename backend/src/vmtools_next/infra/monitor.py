"""System Monitor — collects CPU, memory, disk, network, and bot process metrics.

Uses psutil to collect system metrics at regular intervals.
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from collections import deque
from typing import Optional

import psutil

logger = logging.getLogger("vmtools.monitor")


def _get_disk_path() -> str:
    """Get the appropriate disk path for the current OS."""
    if os.name == "nt":
        return os.environ.get("SYSTEMDRIVE", "C:\\")
    return "/"


class MonitorCollector:
    """Collects system metrics at regular intervals.

    采集项：
      - CPU / 内存 / 磁盘（百分比 + 绝对值）
      - 网络速率（bytes/s，相对上次采样的增量）
      - 项目相关进程（mineflayer node / MCC / uvicorn）的 CPU 与内存
    每次采样后通过 Socket.IO 广播最新指标与进程快照（前端实时刷新，无需轮询）。
    """

    def __init__(self, interval_seconds: int = 10):
        self._interval = interval_seconds
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._disk_path = _get_disk_path()
        self._max_metrics = 10000
        self._metrics: deque[dict] = deque(maxlen=self._max_metrics)
        # 网络速率：记录上次采样字节数，计算 bytes/s 增量
        self._prev_net: dict = {}
        self._last_collect_ts: float = 0.0
        # 进程快照（最新一轮）
        self._processes: list[dict] = []

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        # 预热：cpu_percent(interval=None) 首次调用恒为 0（psutil 无历史基线）
        try:
            psutil.cpu_percent(interval=None)
        except Exception:
            pass
        self._task = asyncio.create_task(self._collect_loop())
        logger.info("Monitor started (interval=%ds)", self._interval)

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    def get_metrics(self, count: int = 100) -> list[dict]:
        items = list(self._metrics)
        return items[-count:]

    def get_latest(self) -> Optional[dict]:
        return self._metrics[-1] if self._metrics else None

    def get_processes(self) -> list[dict]:
        """最新一轮进程资源快照（[ {name, pid, cpu_percent, mem_mb, cmdline} ]）。"""
        return list(self._processes)

    async def _collect_loop(self) -> None:
        while self._running:
            try:
                metrics = self._collect_system_metrics()
                self._metrics.append(metrics)
                self._processes = self._collect_process_stats()
                # Socket.IO 推送最新指标 + 进程快照（前端实时刷新；无 server 时忽略）
                try:
                    from vmtools_next.data.db import sio
                    await sio.emit("metrics_update", metrics)
                    await sio.emit("monitor_processes", self._processes)
                except Exception:
                    pass
            except Exception as e:
                logger.warning("Metrics collection error: %s", e)
            await asyncio.sleep(self._interval)

    def _collect_system_metrics(self) -> dict:
        """Collect current system metrics."""
        cpu_percent = psutil.cpu_percent(interval=None)
        memory = psutil.virtual_memory()
        disk = psutil.disk_usage(self._disk_path)

        # 网络速率：相对上次采样的增量（bytes/s）；首轮无基线返回 0
        net = psutil.net_io_counters()
        now = time.time()
        sent_rate = recv_rate = 0.0
        if self._prev_net and self._last_collect_ts > 0:
            dt = max(now - self._last_collect_ts, 0.1)
            sent_rate = max(0.0, (net.bytes_sent - self._prev_net.get("bytes_sent", 0)) / dt)
            recv_rate = max(0.0, (net.bytes_recv - self._prev_net.get("bytes_recv", 0)) / dt)
        self._prev_net = {"bytes_sent": net.bytes_sent, "bytes_recv": net.bytes_recv}
        self._last_collect_ts = now

        return {
            "timestamp": now,
            "cpu_percent": cpu_percent,
            "memory_total": memory.total,
            "memory_used": memory.used,
            "memory_percent": memory.percent,
            "disk_total": disk.total,
            "disk_used": disk.used,
            "disk_percent": disk.percent,
            "net_bytes_sent": net.bytes_sent,
            "net_bytes_recv": net.bytes_recv,
            "net_sent_rate": sent_rate,
            "net_recv_rate": recv_rate,
        }

    def _collect_process_stats(self) -> list[dict]:
        """采集项目相关进程的资源占用（mineflayer node / MCC / uvicorn）。

        匹配规则：命令行含 bot_main.js（MF）、MinecraftClient（MCC）、
        或本服务 python/uvicorn 进程。
        每个 bot 进程关联到具体实例（优先读 VMT_INSTANCE_ID 环境变量，
        兜底用 mcc_instances.pid 映射），输出 instance_id / instance_name。
        """
        # 每轮轻量查询一次实例 pid → 实例信息（10s 一次，实例数少，可接受）
        instance_by_pid: dict[int, dict] = {}
        try:
            from vmtools_next.data.db import get_session_factory
            from vmtools_next.data.models.mcc_remote import MccInstanceModel
            Session = get_session_factory()
            db = Session()
            try:
                rows = db.query(
                    MccInstanceModel.instance_id,
                    MccInstanceModel.display_name,
                    MccInstanceModel.slug,
                    MccInstanceModel.bot_engine,
                    MccInstanceModel.mc_username,
                    MccInstanceModel.pid,
                ).filter(
                    MccInstanceModel.deleted_at.is_(None),
                    MccInstanceModel.pid.isnot(None),
                ).all()
                for r in rows:
                    if r[5]:
                        instance_by_pid[r[5]] = {
                            "instance_id": r[0],
                            "instance_name": (r[1] or r[2] or r[0])[:40],
                            "engine": r[3] or "mcc",
                            "mc_username": r[4] or "",
                        }
            finally:
                db.close()
        except Exception:
            pass

        results: list[dict] = []
        try:
            for proc in psutil.process_iter(["pid", "name", "cmdline"]):
                try:
                    cmdline = " ".join(proc.info.get("cmdline") or [])
                    name = proc.info.get("name") or ""
                    if not cmdline and not name:
                        continue
                    lower = (cmdline + " " + name).lower()
                    is_bot = "bot_main.js" in lower
                    is_mcc = "minecraftclient" in lower
                    is_self = ("uvicorn" in lower or lower.startswith("python")) and ("vmtools" in lower or "vmtools_next" in lower)
                    if not (is_bot or is_mcc or is_self):
                        continue
                    try:
                        cpu = proc.cpu_percent(interval=None)
                        mem = proc.memory_info().rss / (1024 * 1024)
                    except Exception:
                        continue

                    role = "mineflayer" if is_bot else ("mcc" if is_mcc else "server")
                    pid = proc.pid

                    # 关联实例：优先 VMT_INSTANCE_ID 环境变量（MCC/MF 启动时注入）
                    instance_id: str | None = None
                    instance_name: str | None = None
                    try:
                        env_inst = proc.environ().get("VMT_INSTANCE_ID")
                        if env_inst:
                            instance_id = env_inst
                    except Exception:
                        env_inst = None
                    if not instance_id:
                        info = instance_by_pid.get(pid)
                        if info:
                            instance_id = info["instance_id"]
                            instance_name = info["instance_name"]
                    if instance_id and not instance_name:
                        # 环境变量方式命中实例 id 时，从映射反查名字
                        for info in instance_by_pid.values():
                            if info["instance_id"] == instance_id:
                                instance_name = info["instance_name"]
                                break

                    results.append({
                        "name": name,
                        "pid": pid,
                        "cpu_percent": round(cpu, 1),
                        "mem_mb": round(mem, 1),
                        "cmdline": cmdline[:160],
                        "role": role,
                        "instance_id": instance_id,
                        "instance_name": instance_name,
                    })
                except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                    continue
            results.sort(key=lambda p: p.get("mem_mb", 0), reverse=True)
        except Exception as e:
            logger.debug("Process stats collection error: %s", e)
        return results