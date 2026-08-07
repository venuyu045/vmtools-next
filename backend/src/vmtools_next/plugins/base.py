"""Plugin Base — IPlugin abstract base class.

Defines the plugin lifecycle: load → start → stop → reload.
Plugins receive a PluginContext with access to core services.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from vmtools_next.core.task_engine import TaskEngine
    from vmtools_next.adapters.mcc.mcc_session_pool import MccSessionPool
    from vmtools_next.adapters.mineflayer.mineflayer_session_pool import MineflayerSessionPool

# Runtime type alias — both pool types have the same interface (get_client, etc.)
PluginPool = Any


class PluginContext:
    """Context provided to plugins during initialization."""

    def __init__(self, task_engine: TaskEngine, pool: PluginPool):
        self.task_engine = task_engine
        self.pool = pool

    @property
    def warehouse_manager(self):
        return self.task_engine.warehouse_manager

    @property
    def operation_logger(self):
        return self.task_engine.operation_logger


class IPlugin(ABC):
    """Abstract base class for all plugins.

    ``engine`` 标识插件服务的 bot 引擎：当前插件体系仅服务
    ``mineflayer``（MCC 为固定 C# 客户端，不需要额外插件）。
    """

    name: str = "unnamed"
    version: str = "0.0.1"
    engine: str = "mineflayer"
    description: str = ""

    @abstractmethod
    async def load(self, context: PluginContext) -> None:
        """Initialize the plugin with context."""
        ...

    @abstractmethod
    async def start(self) -> None:
        """Start the plugin (called after load)."""
        ...

    @abstractmethod
    async def stop(self) -> None:
        """Stop the plugin."""
        ...

    @abstractmethod
    async def reload(self) -> None:
        """Reload the plugin configuration."""
        ...

    async def on_event(self, event_type: str, payload: dict) -> None:
        """Handle an event from the event bus. Override to subscribe."""
        pass
