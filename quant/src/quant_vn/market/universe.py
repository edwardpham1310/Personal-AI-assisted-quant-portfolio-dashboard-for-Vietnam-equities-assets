"""Stock universe definitions for Vietnam market research."""

from __future__ import annotations

from pathlib import Path

import yaml


# Default VN30 constituents (as of 2024 — update as needed)
VN30_SYMBOLS = [
    "ACB", "BCM", "BID", "BVH", "CTG",
    "FPT", "GAS", "GVR", "HDB", "HPG",
    "MBB", "MSN", "MWG", "NVL", "PDR",
    "PLX", "POW", "SAB", "SHB", "SSB",
    "SSI", "STB", "TCB", "TPB", "VCB",
    "VHM", "VIB", "VIC", "VJC", "VNM",
]

# Common blue chips for quick research
BLUE_CHIPS = [
    "FPT", "MWG", "HPG", "VNM", "VCB",
    "SSI", "VND", "HCM", "VIC", "VHM",
    "MSN", "GAS", "CTG", "BID", "MBB", "TCB",
]

# Exchange listings
HOSE_SYMBOLS = VN30_SYMBOLS  # VN30 is all HOSE
HNX_SYMBOLS: list[str] = []   # Populate as needed


def load_universe_from_yaml(path: str | Path) -> list[str]:
    """
    Load a universe definition from a YAML file.

    Expected format:
        symbols:
          - FPT
          - MWG
          - HPG
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Universe file not found: {path}")
    with open(path) as f:
        data = yaml.safe_load(f) or {}
    symbols = data.get("symbols", [])
    return [s.strip().upper() for s in symbols]


def get_universe(name: str, config_dir: str | Path = "config") -> list[str]:
    """
    Resolve a universe by name.

    Built-in names: vn30, blue_chips, hose
    Otherwise looks for config/{name}.yaml
    """
    name_lower = name.lower().replace("-", "_")
    if name_lower in ("vn30", "vn_30"):
        return list(VN30_SYMBOLS)
    if name_lower in ("blue_chips", "blue-chips"):
        return list(BLUE_CHIPS)
    if name_lower == "hose":
        return list(HOSE_SYMBOLS)

    # Try config directory
    config_path = Path(config_dir) / f"{name}.yaml"
    if config_path.exists():
        return load_universe_from_yaml(config_path)

    raise ValueError(
        f"Unknown universe '{name}'. "
        f"Built-in: vn30, blue_chips, hose. "
        f"Or create config/{name}.yaml with a 'symbols' list."
    )
