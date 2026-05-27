"""Tests for OHLCV normalization."""

from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from quant_vn_data.normalization.normalize_ohlcv import normalize_ohlcv


def _make_raw(symbol="FPT", n=3, source="test"):
    rows = []
    for i in range(n):
        rows.append({
            "symbol": symbol,
            "Date": f"2024-01-{i+1:02d}",
            "Open": 80000.0 + i * 500,
            "High": 82000.0 + i * 500,
            "Low": 79000.0 + i * 500,
            "Close": 81000.0 + i * 500,
            "Volume": 1_000_000 + i * 100_000,
        })
    return pd.DataFrame(rows)


def test_normalize_basic():
    raw = _make_raw()
    result = normalize_ohlcv(raw, source="test", symbol="FPT")
    assert not result.empty
    assert "trading_date" in result.columns
    assert "source" in result.columns
    assert result["source"].iloc[0] == "test"
    assert all(result["close"] > 0)


def test_normalize_column_aliases():
    df = pd.DataFrame([{
        "ticker": "FPT",
        "date": "2024-03-01",
        "open": 85000.0,
        "high": 87000.0,
        "low": 83000.0,
        "close": 86000.0,
        "totalVolume": 2_000_000,
    }])
    result = normalize_ohlcv(df, source="ssi")
    assert "symbol" in result.columns
    assert result["symbol"].iloc[0] == "FPT"
    assert result["volume"].iloc[0] == 2_000_000


def test_normalize_deduplication():
    raw = _make_raw()
    dup = pd.concat([raw, raw])
    result = normalize_ohlcv(dup, source="test", symbol="FPT")
    assert len(result) == 3  # duplicates removed


def test_normalize_empty():
    result = normalize_ohlcv(pd.DataFrame(), source="test")
    assert result.empty


def test_normalize_missing_required_columns():
    df = pd.DataFrame([{"Open": 100, "Close": 110}])
    result = normalize_ohlcv(df, source="test")
    assert result.empty


def test_normalize_bad_date_skipped():
    df = pd.DataFrame([{
        "symbol": "FPT",
        "trading_date": "not-a-date",
        "open": 80000, "high": 82000, "low": 79000, "close": 81000, "volume": 1000000,
    }])
    result = normalize_ohlcv(df, source="test")
    assert result.empty


def test_normalize_sorted_by_date():
    raw = _make_raw(n=5)
    raw = raw.sample(frac=1)  # shuffle
    result = normalize_ohlcv(raw, source="test", symbol="FPT")
    dates = result["trading_date"].tolist()
    assert dates == sorted(dates)
