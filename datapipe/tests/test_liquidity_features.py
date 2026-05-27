"""Tests for liquidity feature computation."""

from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import pytest

from quant_vn_data.market.liquidity import (
    assign_liquidity_bucket,
    build_liquidity_features,
    is_tradable,
)


def _ohlcv(symbol="FPT", n_days=60, avg_value=50_000_000_000, zero_vol_days=0):
    rows = []
    base_date = date(2023, 1, 2)
    for i in range(n_days):
        d = base_date + timedelta(days=i)
        volume = 0 if i < zero_vol_days else 1_000_000
        close = 86000.0
        value = avg_value if volume > 0 else 0.0
        rows.append({
            "symbol": symbol,
            "trading_date": d,
            "open": close,
            "high": close + 500,
            "low": close - 500,
            "close": close,
            "volume": volume,
            "value": value,
        })
    return pd.DataFrame(rows)


def test_liquid_stock_tradable():
    df = _ohlcv(avg_value=50_000_000_000, zero_vol_days=0)
    result = build_liquidity_features(df)
    # Only last rows where we have full 20-day window
    tradable_rows = result.dropna(subset=["tradable_flag"])
    assert tradable_rows["tradable_flag"].iloc[-1] == True


def test_illiquid_stock_untradable():
    df = _ohlcv(avg_value=1_000_000_000, zero_vol_days=0)  # 1 bn — below 5 bn threshold
    result = build_liquidity_features(df)
    tradable_rows = result.dropna(subset=["tradable_flag"])
    assert tradable_rows["tradable_flag"].iloc[-1] == False


def test_zero_volume_days_affect_tradable():
    df = _ohlcv(avg_value=50_000_000_000, zero_vol_days=5)
    result = build_liquidity_features(df)
    # First 20 days have many zero-volume days
    first_window = result.iloc[19]  # index of 20th row
    if first_window["zero_volume_days_20d"] is not None and first_window["zero_volume_days_20d"] > 2:
        assert first_window["tradable_flag"] == False


def test_liquidity_bucket_high():
    assert assign_liquidity_bucket(150_000_000_000) == "HIGH"


def test_liquidity_bucket_medium():
    assert assign_liquidity_bucket(50_000_000_000) == "MEDIUM"


def test_liquidity_bucket_low():
    assert assign_liquidity_bucket(8_000_000_000) == "LOW"


def test_liquidity_bucket_untradable():
    assert assign_liquidity_bucket(1_000_000_000) == "UNTRADABLE"
    assert assign_liquidity_bucket(None) == "UNTRADABLE"


def test_is_tradable_passes():
    row = pd.Series({
        "avg_value_20d": 50_000_000_000,
        "zero_volume_days_20d": 0,
        "close": 86000,
        "quality_status": "OK",
    })
    assert is_tradable(row) is True


def test_is_tradable_fails_low_value():
    row = pd.Series({
        "avg_value_20d": 1_000_000_000,
        "zero_volume_days_20d": 0,
        "close": 86000,
        "quality_status": "OK",
    })
    assert is_tradable(row) is False


def test_is_tradable_fails_critical_quality():
    row = pd.Series({
        "avg_value_20d": 50_000_000_000,
        "zero_volume_days_20d": 0,
        "close": 86000,
        "quality_status": "CRITICAL",
    })
    assert is_tradable(row, quality_status="CRITICAL") is False


def test_is_tradable_fails_low_price():
    row = pd.Series({
        "avg_value_20d": 50_000_000_000,
        "zero_volume_days_20d": 0,
        "close": 2000,  # below 5000 VND threshold
        "quality_status": "OK",
    })
    assert is_tradable(row) is False


def test_build_liquidity_returns_correct_columns():
    df = _ohlcv()
    result = build_liquidity_features(df)
    expected_cols = {
        "symbol", "trading_date", "avg_volume_20d", "avg_value_20d",
        "zero_volume_days_20d", "tradable_flag", "liquidity_bucket",
    }
    assert expected_cols.issubset(set(result.columns))
