from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from .config import get_config


def configure_logging() -> None:
    cfg = get_config()
    log_dir = Path(cfg.paths.log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(log_dir / "webnas.log", maxBytes=5_000_000, backupCount=5)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.handlers.clear()
    root.addHandler(handler)
    root.addHandler(logging.StreamHandler())


logger = logging.getLogger("webnas")
