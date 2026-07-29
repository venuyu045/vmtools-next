"""Abstract adapter interfaces.

These define the contract that all adapter implementations must fulfill.
The MCC MCP implementations are in adapters/mcc/.
The mineflayer implementations are in adapters/mineflayer/.
"""
from vmtools_next.adapters.abstract.baritone import AbstractBaritoneAdapter  # noqa: F401
from vmtools_next.adapters.abstract.bot_agent import AbstractBotAgent  # noqa: F401
from vmtools_next.adapters.abstract.litematica import AbstractLitematicaAdapter  # noqa: F401
from vmtools_next.adapters.abstract.printer import AbstractPrinterAdapter  # noqa: F401
from vmtools_next.adapters.abstract.minihud import AbstractMiniHudAdapter  # noqa: F401
