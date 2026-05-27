"""Volume indicators."""

from __future__ import annotations

import pandas as pd


def volume_sma(series: pd.Series, window: int = 20) -> pd.Series:
    """Rolling average volume over window bars."""
    return series.rolling(window=window, min_periods=window).mean()


def volume_ratio(series: pd.Series, window: int = 20) -> pd.Series:
    """Volume breakout ratio: current volume / average volume."""
    avg = volume_sma(series, window)
    return series / avg.replace(0, float("nan"))


def on_balance_volume(close: pd.Series, volume: pd.Series) -> pd.Series:
    """
    On-Balance Volume (OBV).
    Adds volume on up days, subtracts on down days.
    """
    direction = close.diff().apply(lambda x: 1 if x > 0 else (-1 if x < 0 else 0))
    return (direction * volume).cumsum()
