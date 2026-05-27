"""Liquidity feature computation.

Produces per-symbol/date liquidity metrics and tradable flags.
All rolling windows use min_periods=window to avoid lookahead on partial history.
"""

from __future__ import annotations

import logging
from typing import Any

import pandas as pd

logger = logging.getLogger(__name__)

_BUCKET_THRESHOLDS: dict[str, float] = {
    "HIGH": 100_000_000_000,    # 100 bn VND
    "MEDIUM": 20_000_000_000,   # 20 bn VND
    "LOW": 5_000_000_000,       # 5 bn VND
}

_DEFAULT_TRADABLE_RULES: dict[str, Any] = {
    "min_avg_value_20d_vnd": 5_000_000_000,
    "max_zero_volume_days_20d": 2,
    "min_close_price_vnd": 5_000,
}


def build_liquidity_features(
    df: pd.DataFrame,
    hose_limit_pct: float = 0.07,
    hnx_limit_pct: float = 0.10,
    upcom_limit_pct: float = 0.15,
) -> pd.DataFrame:
    """Compute liquidity features for a single-symbol OHLCV DataFrame.

    Input df must be sorted by trading_date and contain at least:
        trading_date, close, volume, [value], [reference_price], [ceiling_price], [floor_price].

    Returns a DataFrame with one row per trading_date containing all liquidity features.
    """
    if df.empty:
        return pd.DataFrame()

    df = df.copy().sort_values("trading_date")
    df["trading_date"] = pd.to_datetime(df["trading_date"]).dt.date

    symbol = df["symbol"].iloc[0] if "symbol" in df.columns else "UNKNOWN"

    # Compute value if missing (close * volume)
    if "value" not in df.columns or df["value"].isna().all():
        df["value"] = df["close"] * df["volume"]

    # Rolling averages with min_periods to avoid partial-window lookahead
    df["avg_volume_20d"] = df["volume"].rolling(20, min_periods=20).mean()
    df["avg_volume_60d"] = df["volume"].rolling(60, min_periods=60).mean()
    df["avg_value_20d"] = df["value"].rolling(20, min_periods=20).mean()
    df["avg_value_60d"] = df["value"].rolling(60, min_periods=60).mean()

    # Zero-volume days
    zero_vol = (df["volume"] == 0).astype(int)
    df["zero_volume_days_20d"] = zero_vol.rolling(20, min_periods=20).sum().astype("Int64")
    df["zero_volume_days_60d"] = zero_vol.rolling(60, min_periods=60).sum().astype("Int64")

    # Limit-up / limit-down days (requires ceiling/floor)
    if "ceiling_price" in df.columns and "floor_price" in df.columns:
        limit_up = (df["close"] >= df["ceiling_price"] * 0.999).astype(int)
        limit_down = (df["close"] <= df["floor_price"] * 1.001).astype(int)
        df["limit_up_days_20d"] = limit_up.rolling(20, min_periods=20).sum().astype("Int64")
        df["limit_down_days_20d"] = limit_down.rolling(20, min_periods=20).sum().astype("Int64")
    else:
        df["limit_up_days_20d"] = None
        df["limit_down_days_20d"] = None

    # Turnover estimate (value / market_cap is unknown — use value as proxy)
    df["turnover_estimate"] = df["avg_value_20d"]

    # Liquidity bucket
    df["liquidity_bucket"] = df["avg_value_20d"].apply(assign_liquidity_bucket)

    # Tradable flag
    df["tradable_flag"] = df.apply(
        lambda r: is_tradable(r, **_DEFAULT_TRADABLE_RULES), axis=1
    )

    df["symbol"] = symbol

    keep_cols = [
        "symbol", "trading_date",
        "avg_volume_20d", "avg_volume_60d",
        "avg_value_20d", "avg_value_60d",
        "zero_volume_days_20d", "zero_volume_days_60d",
        "limit_up_days_20d", "limit_down_days_20d",
        "turnover_estimate", "tradable_flag", "liquidity_bucket",
    ]
    return df[[c for c in keep_cols if c in df.columns]].reset_index(drop=True)


def assign_liquidity_bucket(avg_value_20d: float | None) -> str:
    if avg_value_20d is None or pd.isna(avg_value_20d):
        return "UNTRADABLE"
    if avg_value_20d >= _BUCKET_THRESHOLDS["HIGH"]:
        return "HIGH"
    if avg_value_20d >= _BUCKET_THRESHOLDS["MEDIUM"]:
        return "MEDIUM"
    if avg_value_20d >= _BUCKET_THRESHOLDS["LOW"]:
        return "LOW"
    return "UNTRADABLE"


def is_tradable(
    row: pd.Series,
    min_avg_value_20d_vnd: float = 5_000_000_000,
    max_zero_volume_days_20d: int = 2,
    min_close_price_vnd: float = 5_000,
    quality_status: str | None = None,
) -> bool:
    avg_val = row.get("avg_value_20d")
    zero_days = row.get("zero_volume_days_20d")
    close = row.get("close")
    q_status = quality_status or row.get("quality_status", "OK")

    if q_status == "CRITICAL":
        return False
    if avg_val is None or pd.isna(avg_val) or avg_val < min_avg_value_20d_vnd:
        return False
    if zero_days is not None and not pd.isna(zero_days) and int(zero_days) > max_zero_volume_days_20d:
        return False
    if close is not None and not pd.isna(close) and float(close) < min_close_price_vnd:
        return False
    return True
