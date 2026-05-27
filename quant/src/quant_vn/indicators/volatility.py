"""Volatility indicators: ATR, rolling volatility, Bollinger Bands."""

from __future__ import annotations

import numpy as np
import pandas as pd


def true_range(df: pd.DataFrame) -> pd.Series:
    """
    True Range: max(high-low, |high-prev_close|, |low-prev_close|).
    Requires columns: high, low, close.
    """
    prev_close = df["close"].shift(1)
    tr = pd.concat([
        df["high"] - df["low"],
        (df["high"] - prev_close).abs(),
        (df["low"] - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr


def atr(df: pd.DataFrame, window: int = 14) -> pd.Series:
    """Average True Range using Wilder's smoothing."""
    tr = true_range(df)
    return tr.ewm(alpha=1 / window, min_periods=window, adjust=False).mean()


def rolling_volatility(series: pd.Series, window: int = 20, annualize: bool = True) -> pd.Series:
    """
    Rolling annualised volatility of log returns.
    annualize=True multiplies by sqrt(252).
    """
    log_ret = np.log(series / series.shift(1))
    vol = log_ret.rolling(window=window, min_periods=window).std()
    if annualize:
        vol = vol * np.sqrt(252)
    return vol


def bollinger_bands(
    series: pd.Series,
    window: int = 20,
    n_std: float = 2.0,
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """
    Bollinger Bands.

    Returns (upper, middle, lower).
    middle = SMA(window), upper/lower = middle ± n_std * rolling_std.
    """
    middle = series.rolling(window=window, min_periods=window).mean()
    std = series.rolling(window=window, min_periods=window).std()
    upper = middle + n_std * std
    lower = middle - n_std * std
    return upper, middle, lower


def bb_percent_b(series: pd.Series, window: int = 20, n_std: float = 2.0) -> pd.Series:
    """Bollinger Bands %B: position of price within the bands (0=lower, 1=upper)."""
    upper, middle, lower = bollinger_bands(series, window, n_std)
    band_width = upper - lower
    return (series - lower) / band_width.replace(0, float("nan"))
