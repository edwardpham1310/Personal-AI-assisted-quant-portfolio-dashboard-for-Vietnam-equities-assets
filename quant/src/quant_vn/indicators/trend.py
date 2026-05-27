"""Trend indicators: SMA, EMA, moving average crossover."""

from __future__ import annotations

import pandas as pd


def sma(series: pd.Series, window: int) -> pd.Series:
    """Simple Moving Average. First (window-1) values are NaN."""
    return series.rolling(window=window, min_periods=window).mean()


def ema(series: pd.Series, window: int) -> pd.Series:
    """Exponential Moving Average. Uses min_periods=window to avoid partial warmup bias."""
    return series.ewm(span=window, min_periods=window, adjust=False).mean()


def ma_crossover_signal(
    series: pd.Series,
    fast_window: int,
    slow_window: int,
    method: str = "sma",
) -> pd.Series:
    """
    Moving average crossover signal.

    Returns Series of {1, 0, -1}:
      1 = fast MA just crossed above slow MA (buy)
     -1 = fast MA just crossed below slow MA (sell)
      0 = no crossover

    No lookahead: uses only data at or before each index.
    """
    if fast_window >= slow_window:
        raise ValueError(f"fast_window ({fast_window}) must be < slow_window ({slow_window})")

    fn = sma if method == "sma" else ema
    fast = fn(series, fast_window)
    slow = fn(series, slow_window)

    above = (fast > slow).astype(int)
    signal = above.diff()
    signal = signal.where(signal != 0, 0)
    return signal.fillna(0).astype(int)


def ma_position_signal(
    series: pd.Series,
    fast_window: int,
    slow_window: int,
    method: str = "sma",
) -> pd.Series:
    """
    Level-based MA signal (not just crossover events).

    Returns 1 when fast > slow, 0 otherwise.
    This is the persistent position: hold long while fast MA > slow MA.
    """
    if fast_window >= slow_window:
        raise ValueError(f"fast_window ({fast_window}) must be < slow_window ({slow_window})")

    fn = sma if method == "sma" else ema
    fast = fn(series, fast_window)
    slow = fn(series, slow_window)

    signal = (fast > slow).astype(float)
    signal[fast.isna() | slow.isna()] = float("nan")
    return signal
