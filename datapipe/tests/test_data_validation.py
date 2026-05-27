"""Tests for OHLCV data validation checks."""

from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from quant_vn_data.validation.ohlcv_checks import Severity, validate_ohlcv


def _row(**kwargs):
    defaults = {
        "symbol": "FPT",
        "trading_date": date(2024, 1, 2),
        "source": "test",
        "open": 85000.0,
        "high": 87000.0,
        "low": 83000.0,
        "close": 86000.0,
        "volume": 1_000_000,
        "value": 86_000_000_000.0,
    }
    defaults.update(kwargs)
    return defaults


def _df(*rows):
    return pd.DataFrame(rows)


def test_valid_row_no_issues():
    df = _df(_row())
    _, issues = validate_ohlcv(df)
    critical = [i for i in issues if i.severity == Severity.CRITICAL]
    assert not critical


def test_high_less_than_low():
    df = _df(_row(high=80000.0, low=90000.0))
    _, issues = validate_ohlcv(df)
    types = [i.issue_type for i in issues]
    assert "HIGH_LESS_THAN_LOW" in types


def test_close_above_high():
    df = _df(_row(close=90000.0, high=87000.0))
    _, issues = validate_ohlcv(df)
    types = [i.issue_type for i in issues]
    assert "CLOSE_ABOVE_HIGH" in types


def test_close_below_low():
    df = _df(_row(close=80000.0, low=83000.0))
    _, issues = validate_ohlcv(df)
    types = [i.issue_type for i in issues]
    assert "CLOSE_BELOW_LOW" in types


def test_open_above_high():
    df = _df(_row(open=90000.0, high=87000.0))
    _, issues = validate_ohlcv(df)
    types = [i.issue_type for i in issues]
    assert "OPEN_ABOVE_HIGH" in types


def test_open_below_low():
    df = _df(_row(open=80000.0, low=83000.0))
    _, issues = validate_ohlcv(df)
    types = [i.issue_type for i in issues]
    assert "OPEN_BELOW_LOW" in types


def test_negative_volume():
    df = _df(_row(volume=-100))
    _, issues = validate_ohlcv(df)
    types = [i.issue_type for i in issues]
    assert "NEGATIVE_VOLUME" in types


def test_non_positive_price():
    df = _df(_row(close=0.0))
    _, issues = validate_ohlcv(df)
    types = [i.issue_type for i in issues]
    assert "NON_POSITIVE_PRICE" in types


def test_negative_close():
    df = _df(_row(close=-1000.0, high=87000.0, low=83000.0, open=85000.0))
    _, issues = validate_ohlcv(df)
    types = [i.issue_type for i in issues]
    assert "NON_POSITIVE_PRICE" in types


def test_zero_volume_flagged():
    df = _df(_row(volume=0))
    _, issues = validate_ohlcv(df)
    types = [i.issue_type for i in issues]
    assert "ZERO_VOLUME" in types


def test_duplicate_rows_normalized():
    row = _row()
    df = pd.DataFrame([row, row])
    _, issues = validate_ohlcv(df)
    # No crash, issues may include duplicate-related flags


def test_ceiling_breach():
    df = _df(_row(close=95000.0, ceiling_price=87000.0))
    _, issues = validate_ohlcv(df)
    types = [i.issue_type for i in issues]
    assert "CEILING_BREACH" in types


def test_floor_breach():
    df = _df(_row(close=78000.0, floor_price=83000.0))
    _, issues = validate_ohlcv(df)
    types = [i.issue_type for i in issues]
    assert "FLOOR_BREACH" in types


def test_abnormal_price_jump():
    df = pd.DataFrame([
        _row(trading_date=date(2024, 1, 2), close=86000.0),
        _row(trading_date=date(2024, 1, 3), close=120000.0),  # >39% jump
    ])
    _, issues = validate_ohlcv(df, max_price_jump_pct=15.0)
    types = [i.issue_type for i in issues]
    assert "ABNORMAL_PRICE_JUMP" in types


def test_quality_status_annotated():
    df = _df(_row(high=80000.0, low=90000.0))
    annotated, _ = validate_ohlcv(df)
    assert annotated["quality_status"].iloc[0] != "OK"
