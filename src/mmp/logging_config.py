from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from .config import APP_DIR

_INITIALIZED = False


def setup_logging(log_level: int = logging.INFO) -> None:
    """Configure structured rotating file and console logging for MMP."""
    global _INITIALIZED
    if _INITIALIZED:
        return

    APP_DIR.mkdir(parents=True, exist_ok=True)
    log_file = APP_DIR / "mmp.log"

    root_logger = logging.getLogger("mmp")
    root_logger.setLevel(log_level)

    formatter = logging.Formatter(
        fmt="%(asctime)s [%(levelname)s] [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Rotating file handler (2MB max per file, 3 backups)
    try:
        file_handler = RotatingFileHandler(
            log_file,
            maxBytes=2 * 1024 * 1024,
            backupCount=3,
            encoding="utf-8",
        )
        file_handler.setFormatter(formatter)
        file_handler.setLevel(log_level)
        root_logger.addHandler(file_handler)
    except OSError:
        # Fallback if log file cannot be created (e.g. read-only filesystem)
        pass

    # Console handler for dev/terminal execution
    if sys.stderr and sys.stderr.isatty():
        console_handler = logging.StreamHandler(sys.stderr)
        console_handler.setFormatter(formatter)
        console_handler.setLevel(log_level)
        root_logger.addHandler(console_handler)

    _INITIALIZED = True


def get_logger(name: str) -> logging.Logger:
    """Get a logger namespaced under 'mmp'."""
    if not _INITIALIZED:
        setup_logging()
    if name == "mmp" or name.startswith("mmp."):
        return logging.getLogger(name)
    return logging.getLogger(f"mmp.{name}")
