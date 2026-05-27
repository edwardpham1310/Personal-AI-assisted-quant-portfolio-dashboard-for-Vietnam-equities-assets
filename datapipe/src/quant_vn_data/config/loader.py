"""YAML config file loader."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


_CONFIG_ROOT = Path(__file__).parents[4] / "config"


def load_yaml_config(filename: str, config_dir: Path | None = None) -> dict[str, Any]:
    """Load a YAML config file from the config/ directory."""
    root = config_dir or _CONFIG_ROOT
    path = root / filename
    if not path.exists():
        return {}
    with path.open() as f:
        return yaml.safe_load(f) or {}


def load_watchlist(config_dir: Path | None = None) -> list[str]:
    cfg = load_yaml_config("watchlist.yaml", config_dir)
    return cfg.get("symbols", [])


def load_universe(name: str = "universe_vn30.yaml", config_dir: Path | None = None) -> list[str]:
    cfg = load_yaml_config(name, config_dir)
    return cfg.get("symbols", [])


def load_liquidity_config(config_dir: Path | None = None) -> dict[str, Any]:
    return load_yaml_config("liquidity.yaml", config_dir)


def load_validation_config(config_dir: Path | None = None) -> dict[str, Any]:
    return load_yaml_config("validation.yaml", config_dir)
