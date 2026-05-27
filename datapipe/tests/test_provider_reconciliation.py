"""Tests for provider reconciliation logic."""

from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from quant_vn_data.validation.provider_reconciliation import reconcile_providers


def _ohlcv(symbol, dt, close, volume, source):
    return {
        "symbol": symbol,
        "trading_date": dt,
        "close": close,
        "volume": volume,
        "source": source,
    }


def test_identical_rows_match():
    dt = date(2024, 1, 2)
    pri = pd.DataFrame([_ohlcv("FPT", dt, 86000.0, 1_000_000, "ssi")])
    sec = pd.DataFrame([_ohlcv("FPT", dt, 86000.0, 1_000_000, "vnstock")])

    result = reconcile_providers(pri, sec, "ssi", "vnstock", fields=["close", "volume"])
    close_rows = result[result["field_name"] == "close"]
    assert (close_rows["status"] == "MATCH").all()


def test_small_difference_minor():
    dt = date(2024, 1, 2)
    pri = pd.DataFrame([_ohlcv("FPT", dt, 86000.0, 1_000_000, "ssi")])
    sec = pd.DataFrame([_ohlcv("FPT", dt, 86050.0, 1_000_000, "vnstock")])  # 0.058% diff

    result = reconcile_providers(pri, sec, "ssi", "vnstock", fields=["close"])
    close_rows = result[result["field_name"] == "close"]
    assert (close_rows["status"].isin(["MATCH", "MINOR_DIFFERENCE"])).all()


def test_large_difference_major():
    dt = date(2024, 1, 2)
    pri = pd.DataFrame([_ohlcv("FPT", dt, 86000.0, 1_000_000, "ssi")])
    sec = pd.DataFrame([_ohlcv("FPT", dt, 70000.0, 1_000_000, "vnstock")])  # >16% diff

    result = reconcile_providers(pri, sec, "ssi", "vnstock", fields=["close"])
    close_rows = result[result["field_name"] == "close"]
    assert (close_rows["status"] == "MAJOR_DIFFERENCE").all()


def test_missing_secondary():
    dt = date(2024, 1, 2)
    pri = pd.DataFrame([_ohlcv("FPT", dt, 86000.0, 1_000_000, "ssi")])
    sec = pd.DataFrame()

    result = reconcile_providers(pri, sec, "ssi", "vnstock", fields=["close"])
    assert not result.empty
    assert (result["status"] == "MISSING_SECONDARY").all()


def test_missing_primary():
    dt = date(2024, 1, 2)
    pri = pd.DataFrame()
    sec = pd.DataFrame([_ohlcv("FPT", dt, 86000.0, 1_000_000, "vnstock")])

    result = reconcile_providers(pri, sec, "ssi", "vnstock", fields=["close"])
    assert not result.empty
    assert (result["status"] == "MISSING_PRIMARY").all()


def test_empty_both_returns_empty():
    result = reconcile_providers(pd.DataFrame(), pd.DataFrame(), "ssi", "vnstock")
    assert result.empty


def test_multiple_dates():
    dates = [date(2024, 1, 2), date(2024, 1, 3), date(2024, 1, 4)]
    pri = pd.DataFrame([_ohlcv("FPT", d, 86000.0 + i * 100, 1_000_000, "ssi") for i, d in enumerate(dates)])
    sec = pd.DataFrame([_ohlcv("FPT", d, 86000.0 + i * 100, 1_000_000, "vnstock") for i, d in enumerate(dates)])

    result = reconcile_providers(pri, sec, "ssi", "vnstock", fields=["close"])
    assert len(result) == 3  # 3 dates × 1 field
    assert (result["status"] == "MATCH").all()
