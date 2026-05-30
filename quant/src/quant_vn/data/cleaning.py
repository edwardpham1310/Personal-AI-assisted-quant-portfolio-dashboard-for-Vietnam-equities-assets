"""OHLCV data cleaning pipeline."""

from __future__ import annotations

import datetime
import logging

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


# Threshold for flagging a single-day price change as suspicious.
# HOSE limit is ±7%, HNX is ±10%. A move above 7.5% on HOSE is likely a data error.
_SPIKE_THRESHOLD = 0.075


def clean_ohlcv(
    df: pd.DataFrame,
    symbol: str,
    *,
    fill_missing: bool = True,
    drop_zero_volume: bool = False,
    spike_threshold: float = _SPIKE_THRESHOLD,
    is_adjusted: bool = False,
) -> tuple[pd.DataFrame, list[dict]]:
    """
    Clean a raw OHLCV DataFrame for one symbol.

    Returns (cleaned_df, issues) where issues is a list of dicts describing
    problems found (non-fatal warnings are kept; fatal errors drop the row).
    """
    issues: list[dict] = []
    df = df.copy()

    # ── 1. Ensure required columns ────────────────────────────────────────
    required = {"date", "open", "high", "low", "close", "volume"}
    missing_cols = required - set(df.columns)
    if missing_cols:
        raise ValueError(f"DataFrame for {symbol} is missing columns: {missing_cols}")

    # ── 2. Parse date ─────────────────────────────────────────────────────
    df["date"] = pd.to_datetime(df["date"]).dt.date

    # ── 3. Sort ───────────────────────────────────────────────────────────
    df = df.sort_values("date").reset_index(drop=True)

    # ── 4. Remove duplicates (keep last) ─────────────────────────────────
    n_before = len(df)
    df = df.drop_duplicates(subset=["date"], keep="last")
    n_dupes = n_before - len(df)
    if n_dupes > 0:
        issues.append({
            "symbol": symbol,
            "issue_type": "duplicate_dates",
            "description": f"{n_dupes} duplicate date(s) removed (kept last)",
            "severity": "warning",
        })

    # ── 5. Cast numeric columns ───────────────────────────────────────────
    for col in ("open", "high", "low", "close"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df["volume"] = pd.to_numeric(df["volume"], errors="coerce").fillna(0).astype(int)

    # ── 6. Drop rows with NaN prices ──────────────────────────────────────
    n_before = len(df)
    null_prices = df[["open", "high", "low", "close"]].isnull().any(axis=1)
    if null_prices.any():
        issues.append({
            "symbol": symbol,
            "issue_type": "null_prices",
            "description": f"{null_prices.sum()} row(s) with null price(s) dropped",
            "severity": "warning",
        })
        df = df[~null_prices].reset_index(drop=True)

    # ── 7. Validate OHLC relationships ────────────────────────────────────
    bad_ohlc = (
        (df["high"] < df["low"])
        | (df["high"] < df["open"])
        | (df["high"] < df["close"])
        | (df["low"] > df["open"])
        | (df["low"] > df["close"])
    )
    if bad_ohlc.any():
        bad_dates = df.loc[bad_ohlc, "date"].tolist()
        issues.append({
            "symbol": symbol,
            "issue_type": "invalid_ohlc",
            "description": f"{bad_ohlc.sum()} row(s) with invalid OHLC relationship on dates {bad_dates[:5]}",
            "severity": "error",
        })
        df = df[~bad_ohlc].reset_index(drop=True)

    # ── 8. Validate non-negative prices ──────────────────────────────────
    non_positive = (df[["open", "high", "low", "close"]] <= 0).any(axis=1)
    if non_positive.any():
        issues.append({
            "symbol": symbol,
            "issue_type": "non_positive_price",
            "description": f"{non_positive.sum()} row(s) with non-positive price dropped",
            "severity": "error",
        })
        df = df[~non_positive].reset_index(drop=True)

    # ── 9. Negative volume ────────────────────────────────────────────────
    neg_vol = df["volume"] < 0
    if neg_vol.any():
        issues.append({
            "symbol": symbol,
            "issue_type": "negative_volume",
            "description": f"{neg_vol.sum()} row(s) with negative volume set to 0",
            "severity": "warning",
        })
        df.loc[neg_vol, "volume"] = 0

    # ── 10. Zero volume days (flag, don't drop by default) ────────────────
    zero_vol = df["volume"] == 0
    if zero_vol.any():
        issues.append({
            "symbol": symbol,
            "issue_type": "zero_volume",
            "description": f"{zero_vol.sum()} trading day(s) with zero volume",
            "severity": "warning",
        })
    if drop_zero_volume:
        df = df[~zero_vol].reset_index(drop=True)

    # ── 11. Price spike detection ─────────────────────────────────────────
    if len(df) > 1:
        close_ret = df["close"].pct_change().abs()
        spikes = close_ret > spike_threshold
        spike_count = spikes.sum()
        if spike_count > 0:
            spike_dates = df.loc[spikes, "date"].tolist()
            issues.append({
                "symbol": symbol,
                "issue_type": "price_spike",
                "description": (
                    f"{spike_count} day(s) with >|{spike_threshold*100:.0f}%| close change: "
                    f"{spike_dates[:5]}"
                ),
                "severity": "warning",
            })

    # ── 12. Fill missing trading days (forward-fill prices, zero volume) ──
    # Uses the Vietnam trading calendar, not Western business days (freq="B").
    # freq="B" would inject phantom rows on Vietnamese holidays (Tet, April 30, etc.).
    if fill_missing and len(df) > 1:
        from ..market.calendar import get_trading_days
        start_date = df["date"].min()
        end_date = df["date"].max()
        # get_trading_days expects datetime.date
        if not isinstance(start_date, datetime.date) or isinstance(start_date, datetime.datetime):
            start_date = pd.Timestamp(start_date).date()
        if not isinstance(end_date, datetime.date) or isinstance(end_date, datetime.datetime):
            end_date = pd.Timestamp(end_date).date()
        trading_days = get_trading_days(start_date, end_date)
        full_range = pd.DatetimeIndex(pd.to_datetime(trading_days))
        df_indexed = df.set_index(pd.to_datetime(df["date"]))
        df_indexed = df_indexed.reindex(full_range)
        n_filled = df_indexed[["close"]].isnull().sum().iloc[0]
        if n_filled > 0:
            df_indexed[["open", "high", "low", "close"]] = (
                df_indexed[["open", "high", "low", "close"]].ffill()
            )
            df_indexed["volume"] = df_indexed["volume"].fillna(0).astype(int)
            df_indexed["date"] = df_indexed.index.date
            issues.append({
                "symbol": symbol,
                "issue_type": "missing_dates",
                "description": f"{n_filled} missing business day(s) forward-filled",
                "severity": "warning",
            })
            df = df_indexed.reset_index(drop=True)

    # ── 13. Add metadata columns ──────────────────────────────────────────
    df["symbol"] = symbol.upper()
    df["is_adjusted"] = is_adjusted

    # ── 14. Final column selection and ordering ───────────────────────────
    keep = ["symbol", "date", "open", "high", "low", "close", "volume", "is_adjusted"]
    extra = [c for c in df.columns if c not in keep]
    df = df[keep + extra]
    df = df.sort_values("date").reset_index(drop=True)

    logger.info(
        "Cleaned %s: %d rows, %d issues", symbol, len(df), len(issues)
    )
    return df, issues
