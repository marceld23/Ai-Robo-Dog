from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config.yaml"
DEFAULT_SECRETS_PATH = PROJECT_ROOT / "secrets.env"


class Config(dict):
    def section(self, name: str) -> dict[str, Any]:
        value = self.get(name, {})
        if not isinstance(value, dict):
            raise TypeError(f"Config section '{name}' must be a mapping, got {type(value).__name__}")
        return value


def load(config_path: Path | str | None = None, secrets_path: Path | str | None = None) -> Config:
    cfg_path = Path(config_path) if config_path else DEFAULT_CONFIG_PATH
    sec_path = Path(secrets_path) if secrets_path else DEFAULT_SECRETS_PATH

    with cfg_path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    if sec_path.exists():
        load_dotenv(sec_path, override=False)

    return Config(data)


def env(name: str, default: str | None = None) -> str | None:
    return os.environ.get(name, default)
