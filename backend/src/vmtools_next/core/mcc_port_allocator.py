"""MCC MCP port allocator."""
from __future__ import annotations

import socket
from contextlib import closing

from sqlalchemy.orm import Session

from vmtools_next.config import get_config
from vmtools_next.data.models.mcc_remote import MccInstanceModel


class MccPortAllocator:
    """Allocate a free MCP port using DB reservations plus socket probing."""

    def __init__(self, start_port: int | None = None, end_port: int | None = None):
        config = get_config().mcc
        self.start_port = start_port or config.instance_start_port
        self.end_port = end_port or config.instance_end_port

    def allocate(self, db: Session, preferred: int | None = None) -> int:
        candidates: list[int] = []
        if preferred is not None:
            candidates.append(preferred)
        candidates.extend(range(self.start_port, self.end_port + 1))

        seen: set[int] = set()
        used_ports = {
            row[0]
            for row in db.query(MccInstanceModel.mcp_port)
            .filter(MccInstanceModel.deleted_at.is_(None))
            .all()
        }
        for port in candidates:
            if port in seen:
                continue
            seen.add(port)
            if port < 1 or port > 65535:
                continue
            if port in used_ports:
                continue
            if self._is_port_available(port):
                return port
        raise RuntimeError(f"No free MCC MCP port in range {self.start_port}-{self.end_port}")

    @staticmethod
    def _is_port_available(port: int) -> bool:
        with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                sock.bind(("127.0.0.1", port))
                return True
            except OSError:
                return False
