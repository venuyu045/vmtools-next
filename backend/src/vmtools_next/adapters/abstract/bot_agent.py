"""Abstract Bot Agent — unified client interface for orchestrators.

Defines a common interface used by BuildStateMachine, MapArtCoordinator,
and BuildEngine. Both MccMcpClient and MineflayerBridgeClient implement
this interface, allowing orchestrators to work with either backend.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Optional


class AbstractBotAgent(ABC):
    """Unified interface for bot control operations.

    Encapsulates the ~15 methods that orchestrators need,
    abstracting away the difference between MCC MCP and mineflayer.
    """

    @property
    @abstractmethod
    def is_connected(self) -> bool:
        """Check if the bot connection is alive."""
        ...

    # ── Block operations ──

    @abstractmethod
    async def place_block(self, x: int, y: int, z: int, face: str = "UP",
                           hand: str = "MAIN_HAND", look_at_block: bool = True) -> dict:
        """Place a block at the specified position."""
        ...

    @abstractmethod
    async def get_world_block_at(self, x: int, y: int, z: int) -> dict:
        """Get block information at the specified position."""
        ...

    @abstractmethod
    async def scan_nearby_blocks(self, radius: int = 16, max_count: int = 100,
                                  matching: str = None) -> dict:
        """Scan for blocks near the player."""
        ...

    # ── Movement / pathfinding ──

    @abstractmethod
    async def move_to(self, x: int, y: int, z: int,
                       max_offset: int = 3, timeout_ms: int = 15000) -> dict:
        """Pathfind to the specified position."""
        ...

    @abstractmethod
    async def look_at(self, x: int, y: int, z: int) -> dict:
        """Look at a specific position."""
        ...

    @abstractmethod
    async def get_player_state(self) -> dict:
        """Get the current player state (position, health, etc.)."""
        ...

    @abstractmethod
    async def is_player_nearby(self, radius: int = 10) -> dict:
        """Check if other players are nearby."""
        ...

    # ── Inventory / hotbar ──

    @abstractmethod
    async def select_hotbar_item(self, item_type: str,
                                  prefer_lowest_slot: bool = True) -> dict:
        """Select an item in the hotbar by type."""
        ...

    @abstractmethod
    async def get_inventory_snapshot(self, inventory_id: int = 0) -> dict:
        """Get a snapshot of the player inventory."""
        ...

    # ── Container operations ──

    @abstractmethod
    async def open_container_at(self, x: int, y: int, z: int,
                                 timeout_ms: int = 5000) -> dict:
        """Open a container at the specified position."""
        ...

    @abstractmethod
    async def close_container(self, container_id: Any,
                               timeout_ms: int = 5000) -> dict:
        """Close an open container."""
        ...

    @abstractmethod
    async def withdraw_container_item(self, item_type: str, count: int = 64,
                                       container_id: Any = None) -> dict:
        """Withdraw items from a container."""
        ...

    @abstractmethod
    async def deposit_container_item(self, item_type: str, count: int = 64,
                                      container_id: Any = None) -> dict:
        """Deposit items into a container."""
        ...

    # ── Chat / commands ──

    @abstractmethod
    async def send_chat(self, message: str) -> dict:
        """Send a chat message."""
        ...

    # ── Connection management ──

    @abstractmethod
    async def connect(self) -> bool:
        """Establish connection to the bot process."""
        ...

    @abstractmethod
    async def disconnect(self) -> None:
        """Disconnect from the bot process."""
        ...
