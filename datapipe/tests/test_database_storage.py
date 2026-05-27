"""Tests for SQLite storage layer."""

from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from quant_vn_data.storage.sqlite_store import SQLiteStore


def _ohlcv_row(**kwargs):
    defaults = {
        "symbol": "FPT",
        "trading_date": date(2024, 1, 2),
        "open": 85000.0, "high": 87000.0, "low": 83000.0, "close": 86000.0,
        "volume": 1_000_000, "value": 86_000_000_000.0,
        "source": "test", "quality_status": "OK", "is_adjusted": False,
    }
    defaults.update(kwargs)
    return defaults


@pytest.fixture
def store(in_memory_db):
    return SQLiteStore(in_memory_db)


def test_upsert_ohlcv_inserts(store):
    df = pd.DataFrame([_ohlcv_row()])
    n = store.upsert_ohlcv(df)
    assert n == 1


def test_upsert_ohlcv_duplicate_skip(store):
    df = pd.DataFrame([_ohlcv_row()])
    store.upsert_ohlcv(df)
    n2 = store.upsert_ohlcv(df)
    assert n2 == 0  # duplicate skipped


def test_query_ohlcv_by_symbol(store):
    df = pd.DataFrame([_ohlcv_row(symbol="FPT"), _ohlcv_row(symbol="MWG", trading_date=date(2024, 1, 3))])
    store.upsert_ohlcv(df)
    result = store.query_ohlcv("FPT")
    assert len(result) == 1
    assert result["symbol"].iloc[0] == "FPT"


def test_query_ohlcv_by_date_range(store):
    rows = [
        _ohlcv_row(trading_date=date(2024, 1, 2)),
        _ohlcv_row(trading_date=date(2024, 1, 3)),
        _ohlcv_row(trading_date=date(2024, 1, 4)),
    ]
    store.upsert_ohlcv(pd.DataFrame(rows))
    result = store.query_ohlcv("FPT", start_date="2024-01-03", end_date="2024-01-04")
    assert len(result) == 2


def test_query_ohlcv_empty(store):
    result = store.query_ohlcv("NONEXISTENT")
    assert result.empty


def test_upsert_symbols(store):
    df = pd.DataFrame([{
        "symbol": "FPT", "exchange": "HOSE", "name": "FPT Corp",
        "type": "STOCK", "status": "LISTED", "source": "ssi",
    }])
    n = store.upsert_symbols(df)
    assert n >= 1


def test_table_counts(store):
    counts = store.table_counts()
    assert "ohlcv_daily" in counts
    assert "symbols" in counts
    assert isinstance(counts["ohlcv_daily"], int)


def test_insert_corporate_actions(store):
    df = pd.DataFrame([{
        "symbol": "FPT",
        "action_type": "CASH_DIVIDEND",
        "cash_dividend": 2000.0,
        "source": "vsdc",
        "parse_status": "PARSED",
    }])
    n = store.insert_corporate_actions(df)
    assert n == 1


def test_insert_quality_issues(store):
    df = pd.DataFrame([{
        "symbol": "FPT",
        "trading_date": date(2024, 1, 2),
        "source": "test",
        "issue_type": "ZERO_VOLUME",
        "severity": "INFO",
        "message": "zero volume day",
    }])
    n = store.insert_quality_issues(df)
    assert n == 1


def test_upsert_liquidity(store):
    df = pd.DataFrame([{
        "symbol": "FPT",
        "trading_date": date(2024, 1, 31),
        "avg_volume_20d": 1_000_000.0,
        "avg_value_20d": 86_000_000_000.0,
        "zero_volume_days_20d": 0,
        "tradable_flag": True,
        "liquidity_bucket": "HIGH",
    }])
    n = store.upsert_liquidity(df)
    assert n >= 1

    # Upsert again — should update, not duplicate
    n2 = store.upsert_liquidity(df)
    result = store.query_liquidity("FPT")
    assert len(result) == 1


def test_bulk_update_quality_status(store):
    store.upsert_ohlcv(pd.DataFrame([_ohlcv_row()]))
    annotated = pd.DataFrame([{
        "symbol": "FPT",
        "trading_date": date(2024, 1, 2),
        "source": "test",
        "quality_status": "HIGH",
    }])
    updated = store.bulk_update_quality_status(annotated)
    assert updated == 1
    result = store.query_ohlcv("FPT")
    assert result["quality_status"].iloc[0] == "HIGH"


def test_bulk_update_quality_status_skips_ok_rows(store):
    store.upsert_ohlcv(pd.DataFrame([_ohlcv_row()]))
    annotated = pd.DataFrame([{
        "symbol": "FPT",
        "trading_date": date(2024, 1, 2),
        "source": "test",
        "quality_status": "OK",
    }])
    updated = store.bulk_update_quality_status(annotated)
    assert updated == 0
