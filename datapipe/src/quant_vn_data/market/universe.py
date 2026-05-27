"""Symbol universe helpers."""

from __future__ import annotations

from pathlib import Path

from quant_vn_data.config.loader import load_watchlist, load_universe


class Universe:
    @staticmethod
    def vn30(config_dir: Path | None = None) -> list[str]:
        return load_universe("universe_vn30.yaml", config_dir)

    @staticmethod
    def watchlist(config_dir: Path | None = None) -> list[str]:
        return load_watchlist(config_dir)
