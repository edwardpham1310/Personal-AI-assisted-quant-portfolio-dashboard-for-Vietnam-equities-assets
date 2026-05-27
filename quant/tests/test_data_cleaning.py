"""Tests for data cleaning and validation."""

from __future__ import annotations

import datetime

import numpy as np
import pandas as pd
import pytest

from quant_vn.data.cleaning import clean_ohlcv
from quant_vn.data.validation import validate_ohlcv


def _make_df(**overrides):
    dates = pd.date_range("2020-01-02", periods=5, freq="B")
    data = {
        "date": dates.date,
        "open": [100.0, 101.0, 102.0, 103.0, 104.0],
        "high": [105.0, 106.0, 107.0, 108.0, 109.0],
        "low": [98.0, 99.0, 100.0, 101.0, 102.0],
        "close": [102.0, 103.0, 104.0, 105.0, 106.0],
        "volume": [1_000_000, 900_000, 1_100_000, 800_000, 950_000],
    }
    data.update(overrides)
    return pd.DataFrame(data)


def test_clean_basic_valid_data():
    df = _make_df()
    cleaned, issues = clean_ohlcv(df, symbol="TEST")
    assert len(cleaned) == 5
    assert "symbol" in cleaned.columns
    assert cleaned["symbol"].iloc[0] == "TEST"
    assert len([i for i in issues if i["severity"] == "error"]) == 0


def test_clean_removes_duplicates():
    df = _make_df()
    df = pd.concat([df, df.iloc[:1]]).reset_index(drop=True)
    cleaned, issues = clean_ohlcv(df, symbol="TEST")
    assert len(cleaned) == 5  # duplicate removed
    assert any(i["issue_type"] == "duplicate_dates" for i in issues)


def test_clean_invalid_ohlc_dropped():
    df = _make_df()
    # Make high < low on row 2 → invalid
    df.at[2, "high"] = 90.0
    df.at[2, "low"] = 110.0
    cleaned, issues = clean_ohlcv(df, symbol="TEST", fill_missing=False)
    assert len(cleaned) == 4
    assert any(i["issue_type"] == "invalid_ohlc" for i in issues)


def test_clean_non_positive_price_dropped():
    df = _make_df()
    df.at[1, "close"] = -5.0
    cleaned, issues = clean_ohlcv(df, symbol="TEST", fill_missing=False)
    assert any(i["issue_type"] in ("invalid_ohlc", "non_positive_price") for i in issues)


def test_clean_negative_volume_set_to_zero():
    df = _make_df()
    df.at[0, "volume"] = -100
    cleaned, issues = clean_ohlcv(df, symbol="TEST", fill_missing=False)
    assert cleaned["volume"].iloc[0] == 0
    assert any(i["issue_type"] == "negative_volume" for i in issues)


def test_clean_sort_by_date():
    df = _make_df()
    df = df.iloc[::-1].reset_index(drop=True)  # reverse order
    cleaned, _ = clean_ohlcv(df, symbol="TEST", fill_missing=False)
    dates = list(cleaned["date"])
    assert dates == sorted(dates)


def test_clean_spike_detection():
    df = _make_df()
    # Create a 50% spike on day 3
    df.at[3, "close"] = 200.0
    df.at[3, "high"] = 210.0
    _, issues = clean_ohlcv(df, symbol="TEST", fill_missing=False, spike_threshold=0.20)
    assert any(i["issue_type"] == "price_spike" for i in issues)


def test_validate_clean_data_no_errors():
    df = _make_df()
    cleaned, _ = clean_ohlcv(df, symbol="TEST", fill_missing=False)
    report = validate_ohlcv(cleaned, symbol="TEST")
    assert report.total_rows == 5
    assert not report.has_errors


def test_validate_detects_invalid_ohlc():
    df = _make_df()
    df.at[1, "high"] = 50.0  # high < low
    report = validate_ohlcv(df, symbol="TEST")
    assert report.invalid_ohlc_rows > 0
    assert report.has_errors


def test_validate_zero_volume_flagged():
    df = _make_df()
    df.at[0, "volume"] = 0
    report = validate_ohlcv(df, symbol="TEST")
    assert report.zero_volume_days > 0
