from __future__ import annotations

import logging
from typing import Any


def setup(cfg: dict[str, Any] | None = None) -> logging.Logger:
    cfg = cfg or {}
    level = cfg.get("level", "INFO")
    fmt = cfg.get("format", "%(asctime)s [%(levelname)s] %(name)s: %(message)s")

    root = logging.getLogger()
    root.handlers.clear()
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter(fmt))
    root.addHandler(handler)
    root.setLevel(level)

    return logging.getLogger("aidog")
