"""Loguru logging setup with rotation and optional ELK hook.

Configured via config/logging.yaml. In production, logs go to:
  - console (INFO+)
  - logs/vmtools-next.log (DEBUG+, 10MB rotation, 30 days retention)
  - logs/vmtools-next-error.log (ERROR+, separate file)
"""
from __future__ import annotations

import sys
import pathlib
from loguru import logger


def setup_logging(log_dir: str = "logs", debug: bool = False) -> None:
    """Configure loguru with sensible defaults.

    Args:
        log_dir: Directory for log files.
        debug: If True, set console level to DEBUG.
    """
    # Remove default handler
    logger.remove()

    # Console handler
    console_level = "DEBUG" if debug else "INFO"
    logger.add(
        sys.stderr,
        level=console_level,
        format=(
            "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
            "<level>{level: <8}</level> | "
            "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> | "
            "{message}"
        ),
        colorize=True,
    )

    # Ensure log directory exists
    log_path = pathlib.Path(log_dir)
    log_path.mkdir(parents=True, exist_ok=True)

    # Main log file (DEBUG+, 10MB rotation, 30 days, zip)
    logger.add(
        log_path / "vmtools-next.log",
        level="DEBUG",
        format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} | {message}",
        rotation="10 MB",
        retention="30 days",
        compression="zip",
        encoding="utf-8",
        enqueue=True,  # thread-safe async writing
    )

    # Error log file (ERROR+ only)
    logger.add(
        log_path / "vmtools-next-error.log",
        level="ERROR",
        format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} | {message}",
        rotation="10 MB",
        retention="30 days",
        compression="zip",
        encoding="utf-8",
        enqueue=True,
    )

    logger.info("Logging initialized (log_dir={}, debug={})", log_dir, debug)


def get_logger(name: str = "vmtools_next"):
    """Get a logger instance bound to a module name."""
    return logger.bind(name=name)
