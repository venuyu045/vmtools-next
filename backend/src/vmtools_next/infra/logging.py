"""Loguru logging setup with rotation and optional ELK hook.

Configured via config/logging.yaml. In production, logs go to:
  - console (INFO+)
  - logs/vmtools-next.log (DEBUG+, 10MB rotation, 30 days retention)
  - logs/vmtools-next-error.log (ERROR+, separate file)
"""
from __future__ import annotations

import logging
import sys
import pathlib
from loguru import logger


class InterceptHandler(logging.Handler):
    """Bridge stdlib ``logging`` records into loguru.

    Modules that still use ``import logging`` (plugins, config_watcher,
    mineflayer/mcc adapters, ...) otherwise only surface WARNING+ via the
    stdlib lastResort handler — their INFO lines (e.g. "Bot replied",
    "Config watcher started") stay invisible under loguru. This handler
    routes everything (level 0) through loguru so INFO is visible too.
    """

    def emit(self, record: logging.LogRecord) -> None:
        try:
            level = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno
        frame, depth = logging.currentframe(), 2
        while frame and frame.f_code.co_filename == logging.__file__:
            frame = frame.f_back
            depth += 1
        logger.opt(depth=depth, exception=record.exc_info).log(level, record.getMessage())


def setup_logging(log_dir: str = "logs", debug: bool = False) -> None:
    """Configure loguru with sensible defaults.

    Args:
        log_dir: Directory for log files.
        debug: If True, set console level to DEBUG.
    """
    # Bridge stdlib logging → loguru so INFO from remaining stdlib loggers is visible.
    logging.basicConfig(handlers=[InterceptHandler()], level=0, force=True)

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
