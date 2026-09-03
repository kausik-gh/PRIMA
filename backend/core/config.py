"""Load prima_config.yaml once.

New code reads this module. Leftover sim scripts may still import
backend/config.py; do not point this file at that module.
"""

from __future__ import annotations

import hashlib
import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

# backend/core/config.py -> repository root
CONFIG_PATH = Path(__file__).resolve().parents[2] / "prima_config.yaml"


def _read_config_bytes() -> bytes:
    if not CONFIG_PATH.is_file():
        raise FileNotFoundError(
            f"PRIMA config file missing: {CONFIG_PATH}. "
            "Create prima_config.yaml at the repository root."
        )
    return CONFIG_PATH.read_bytes()


@lru_cache(maxsize=1)
def get_config() -> dict[str, Any]:
    """Return the YAML mapping, with env overrides applied."""
    raw = yaml.safe_load(_read_config_bytes())
    if not isinstance(raw, dict):
        raise ValueError(f"PRIMA config is not a mapping: {CONFIG_PATH}")

    env_url = os.environ.get("DATABASE_URL")
    if env_url:
        raw.setdefault("database", {})["url"] = env_url

    # LAN demo origin, never a wildcard.
    lan_origin = os.environ.get("PRIMA_LAN_ORIGIN")
    if lan_origin:
        origins = raw.setdefault("cors", {}).setdefault("allow_origins", [])
        if lan_origin not in origins:
            origins.append(lan_origin)

    return raw


@lru_cache(maxsize=1)
def get_config_version() -> str:
    """version:sha256[:12] stored later on risk_decisions.config_version."""
    file_bytes = _read_config_bytes()
    parsed = yaml.safe_load(file_bytes)
    version = "0"
    if isinstance(parsed, dict) and parsed.get("version") is not None:
        version = str(parsed["version"])
    digest = hashlib.sha256(file_bytes).hexdigest()[:12]
    return f"{version}:{digest}"
