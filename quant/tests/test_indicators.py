"""Tests for technical indicators."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from quant_vn.indicators.trend import sma, ema, ma_position_signal
from quant_vn.indicators.momentum import rsi, rate_of_change, momentum
from quant_vn.indicators.volatility import atr, rolling_volatility, bollinger_bands
from quant_vn.indicators.volume import volume_sma, volume_ratio


@pytest.fixture
def close():
    rng = np.random.default_rng(0)
    prices = 100 * np.exp(np.cumsum(rng.normal(0, 0.01, 200)))
    return pd.Series(prices, name="close")


@pytest.fixture
def ohlcv_df(close):
    n = len(close)
    rng = np.random.default_rng(1)
    high = close * (1 + rng.uniform(0, 0.015, n))
    low = close * (1 - rng.uniform(0, 0.015, n))
    return pd.DataFrame({
        "open": close,
        "high": high,
        "low": low,
        "close": close,
        "volume": rng.integers(500_000, 2_000_000, n),
    })


# ── SMA tests ─────────────────────────────────────────────────────────────────

def test_sma_length(close):
    result = sma(close, 20)
    assert len(result) == len(close)


def test_sma_nan_warmup(close):
    result = sma(close, 20)
    assert result.iloc[:19].isna().all()
    assert not result.iloc[19:].isna().any()


def test_sma_value_correctness(close):
    result = sma(close, 5)
    expected = close.iloc[4:9].mean()
    assert abs(result.iloc[8] - expected) < 1e-9


def test_sma_no_lookahead(close):
    # Remove last 10 rows; SMA on shortened series must match original up to the cutoff
    result_full = sma(close, 10)
    result_short = sma(close.iloc[:-10], 10)
    common_idx = result_short.index
    pd.testing.assert_series_equal(
        result_full[common_idx], result_short, check_names=False
    )


# ── EMA tests ─────────────────────────────────────────────────────────────────

def test_ema_length_and_no_early_values(close):
    result = ema(close, 20)
    assert len(result) == len(close)
    assert result.iloc[:19].isna().all()


def test_ema_first_value_within_range_of_sma(close):
    """First non-NaN EMA value should be in the same ballpark as the SMA of the window."""
    window = 10
    ema_vals = ema(close, window)
    sma_vals = sma(close, window)
    # pandas ewm initialises differently from pure SMA-seed; allow 1% tolerance
    assert abs(ema_vals.iloc[window - 1] - sma_vals.iloc[window - 1]) / sma_vals.iloc[window - 1] < 0.01


# ── MA Crossover ──────────────────────────────────────────────────────────────

def test_ma_position_signal_values(close):
    signal = ma_position_signal(close, 10, 30)
    assert set(signal.dropna().unique()).issubset({0.0, 1.0})


def test_ma_position_fast_must_be_less_than_slow(close):
    with pytest.raises(ValueError):
        ma_position_signal(close, 30, 10)


# ── RSI tests ─────────────────────────────────────────────────────────────────

def test_rsi_range(close):
    result = rsi(close, 14)
    valid = result.dropna()
    assert (valid >= 0).all() and (valid <= 100).all()


def test_rsi_nan_warmup(close):
    result = rsi(close, 14)
    assert result.iloc[:13].isna().all()


def test_rsi_constant_series():
    """RSI of a constant series should be NaN (both gains and losses are 0)."""
    s = pd.Series([100.0] * 50)
    result = rsi(s, 14)
    # Constant series → zero gains and zero losses → RSI is undefined (NaN)
    assert result.iloc[14:].isna().all()


def test_rsi_all_up_series():
    """RSI of a monotonically increasing series should approach 100."""
    s = pd.Series(np.linspace(100, 200, 100))
    result = rsi(s, 14)
    assert result.iloc[-1] > 95


# ── ATR tests ─────────────────────────────────────────────────────────────────

def test_atr_positive(ohlcv_df):
    result = atr(ohlcv_df, 14)
    valid = result.dropna()
    assert (valid > 0).all()


def test_atr_nan_warmup(ohlcv_df):
    result = atr(ohlcv_df, 14)
    assert result.iloc[:13].isna().all()


# ── Bollinger Bands tests ─────────────────────────────────────────────────────

def test_bollinger_bands_ordering(close):
    upper, middle, lower = bollinger_bands(close, 20, 2.0)
    valid = ~(upper.isna() | lower.isna())
    assert (upper[valid] >= middle[valid]).all()
    assert (middle[valid] >= lower[valid]).all()


# ── Volume tests ──────────────────────────────────────────────────────────────

def test_volume_ratio_no_lookahead(ohlcv_df):
    vol = ohlcv_df["volume"].astype(float)
    ratio_full = volume_ratio(vol, 20)
    ratio_short = volume_ratio(vol.iloc[:-5], 20)
    # Short version must match full version at its last position
    idx = ratio_short.index[-1]
    assert abs(ratio_full[idx] - ratio_short.iloc[-1]) < 1e-9
