"""Rotating, structured-ish logging. Keep DEBUG=false in normal use to spare the SD card."""
from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

_CONFIGURED = False


def setup_logging(base_dir: Path, debug: bool = False) -> None:
    global _CONFIGURED
    if _CONFIGURED:
        return
    logs_dir = base_dir / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)

    level = logging.DEBUG if debug else logging.INFO
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")

    root = logging.getLogger()
    root.setLevel(level)

    fileh = RotatingFileHandler(logs_dir / "scanner.log", maxBytes=8_000_000, backupCount=4)
    fileh.setFormatter(fmt)
    root.addHandler(fileh)

    console = logging.StreamHandler()
    console.setFormatter(fmt)
    root.addHandler(console)

    _CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
