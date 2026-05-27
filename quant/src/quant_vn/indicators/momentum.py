"""Momentum indicators: RSI, ROC, momentum."""

from __future__ import annotations

import pandas as pd


def rsi(series: pd.Series, window: int = 14) -> pd.Series:
    """
    Wilder's RSI (0–100).

    Uses exponential smoothing (alpha = 1/window) to match the original Wilder method.
    First (window) values are NaN to avoid partial-window lookahead.
    """
    delta = series.diff()
    gains = delta.clip(lower=0)
    losses = (-delta).clip(lower=0)

    # Wilder's smoothing — equivalent to EMA with alpha = 1/window
    avg_gain = gains.ewm(alpha=1 / window, min_periods=window, adjust=False).mean()
    avg_loss = losses.ewm(alpha=1 / window, min_periods=window, adjust=False).mean()

    # RSI = 100 when avg_loss=0 and avg_gain>0 (all gains, no losses)
    # RSI = NaN when both avg_gain=0 and avg_loss=0 (flat/constant series)
    both_zero = (avg_gain == 0) & (avg_loss == 0)
    rs = avg_gain / avg_loss.where(avg_loss != 0, other=float("nan"))
    rsi_val = 100 - (100 / (1 + rs))
    rsi_val = rsi_val.where(avg_loss != 0, other=100.0)  # all gains → RSI 100
    rsi_val = rsi_val.where(~both_zero, other=float("nan"))  # flat → NaN
    return rsi_val


def rate_of_change(series: pd.Series, window: int = 12) -> pd.Series:
    """Rate of Change (ROC): % change over window bars."""
    return series.pct_change(periods=window) * 100


def momentum(series: pd.Series, window: int = 10) -> pd.Series:
    """Price momentum: close - close[window bars ago]."""
    return series - series.shift(window)
