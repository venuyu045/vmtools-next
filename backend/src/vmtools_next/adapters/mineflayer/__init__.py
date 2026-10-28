"""Mineflayer bot adapter package — alternate backend to MCC MCP.

Provides MineflayerBridgeClient (WebSocket client), MineflayerSessionPool,
and 3 adapter implementations (baritone, printer, minihud) that implement the
abstract interfaces in adapters/abstract/.

2026-10-28（索引 §8.2 B6）：`mf_litematica.py`（MfLitematicaAdapter）已删除。
该文件**从未被实例化**，且多处调用 `LitematicaParser` 上不存在的方法
（`parser.parse()` / `get_block_state_at()` / `get_region_names()` ——
`LitematicaParser` 只有 classmethod `parse_file()`），另有漏 `await` 的致命缺陷；
投影解析现役链路是 `adapters/litematica/litematica_parser.py`（地图画 API 直接用）。
"""

from .mineflayer_client import MineflayerBridgeClient
from .mineflayer_session_pool import MineflayerSessionPool
from .mf_baritone import MfBaritoneAdapter
from .mf_printer import MfPrinterAdapter
from .mf_minihud import MfMiniHudAdapter

__all__ = [
    "MineflayerBridgeClient",
    "MineflayerSessionPool",
    "MfBaritoneAdapter",
    "MfPrinterAdapter",
    "MfMiniHudAdapter",
]
