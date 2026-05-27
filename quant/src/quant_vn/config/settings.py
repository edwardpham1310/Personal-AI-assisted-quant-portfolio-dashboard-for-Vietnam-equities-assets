"""Application-wide settings loaded from environment / .env / config/default.yaml."""

from __future__ import annotations

import os
from pathlib import Path

import yaml
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


_ROOT = Path(__file__).resolve().parents[4]  # repo root
_CONFIG_FILE = _ROOT / "config" / "default.yaml"


def _load_yaml_defaults() -> dict:
    if _CONFIG_FILE.exists():
        with open(_CONFIG_FILE) as f:
            return yaml.safe_load(f) or {}
    return {}


_yaml = _load_yaml_defaults()


class CostSettings:
    commission_rate: float = float(
        os.getenv("COMMISSION_RATE", _yaml.get("costs", {}).get("commission_rate", 0.001))
    )
    sell_tax_rate: float = float(
        os.getenv("SELL_TAX_RATE", _yaml.get("costs", {}).get("sell_tax_rate", 0.001))
    )
    slippage_bps: float = float(
        os.getenv("SLIPPAGE_BPS", _yaml.get("costs", {}).get("slippage_bps", 10))
    )
    min_fee: float = float(
        os.getenv("MIN_FEE", _yaml.get("costs", {}).get("min_fee", 0.0))
    )


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Database
    database_url: str = _yaml.get("database", {}).get("url", "sqlite:///data/database/quant_vn.db")

    # Paths (relative to CWD or absolute)
    data_raw_dir: str = _yaml.get("data", {}).get("raw_dir", "data/raw")
    data_processed_dir: str = _yaml.get("data", {}).get("processed_dir", "data/processed")

    # Logging
    log_level: str = _yaml.get("logging", {}).get("level", "INFO")

    # Backtest defaults
    initial_capital: float = float(
        _yaml.get("backtest", {}).get("initial_capital", 100_000_000)
    )
    execution_mode: str = _yaml.get("backtest", {}).get("execution", "next_open")
    allow_short: bool = _yaml.get("backtest", {}).get("allow_short", False)
    annual_trading_days: int = int(
        _yaml.get("backtest", {}).get("annual_trading_days", 252)
    )

    # Cost defaults (can be overridden per backtest run)
    commission_rate: float = float(
        _yaml.get("costs", {}).get("commission_rate", 0.001)
    )
    sell_tax_rate: float = float(
        _yaml.get("costs", {}).get("sell_tax_rate", 0.001)
    )
    slippage_bps: float = float(
        _yaml.get("costs", {}).get("slippage_bps", 10)
    )

    # Reports
    reports_output_dir: str = _yaml.get("reports", {}).get("output_dir", "reports")
    benchmark_symbol: str = _yaml.get("reports", {}).get("benchmark_symbol", "VNINDEX")

    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, v: str) -> str:
        allowed = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        if v.upper() not in allowed:
            raise ValueError(f"log_level must be one of {allowed}")
        return v.upper()

    def raw_dir_path(self) -> Path:
        return Path(self.data_raw_dir)

    def processed_dir_path(self) -> Path:
        return Path(self.data_processed_dir)

    def reports_dir_path(self) -> Path:
        return Path(self.reports_output_dir)


# Module-level singleton — import this everywhere
settings = Settings()
