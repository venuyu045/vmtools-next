"""Mineflayer bot adapter package — alternate backend to MCC MCP.

Provides MineflayerBridgeClient (WebSocket client), MineflayerSessionPool,
and 4 adapter implementations (baritone, printer, litematica, minihud)
that implement the abstract interfaces in adapters/abstract/.
"""

from .mineflayer_client import MineflayerBridgeClient
from .mineflayer_session_pool import MineflayerSessionPool
from .mf_baritone import MfBaritoneAdapter
from .mf_printer import MfPrinterAdapter
from .mf_litematica import MfLitematicaAdapter
from .mf_minihud import MfMiniHudAdapter

__all__ = [
    "MineflayerBridgeClient",
    "MineflayerSessionPool",
    "MfBaritoneAdapter",
    "MfPrinterAdapter",
    "MfLitematicaAdapter",
    "MfMiniHudAdapter",
]
