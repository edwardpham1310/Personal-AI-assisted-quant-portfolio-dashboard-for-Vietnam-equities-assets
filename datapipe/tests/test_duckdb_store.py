"""Tests for DuckDBStore — export, views, absolute path resolution."""

from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from quant_vn_data.storage.database import Database
from quant_vn_data.storage.sqlite_store import SQLiteStore
from quant_vn_data.storage.duckdb_store import DuckDBStore


@pytest.fixture
def populated_sqlite(tmp_path):
    db = Database(f"sqlite:///{tmp_path}/test.sqlite")
    db.create_all()
    store = SQLiteStore(db)
    df = pd.DataFrame([
        {"symbol": "FPT", "trading_date": date(2024, 1, 2), "open": 85000.0,
         "high": 87000.0, "low": 84000.0, "close": 86500.0,
         "volume": 1_200_000, "value": 103_800_000_000.0, "source": "test"},
        {"symbol": "FPT", "trading_date": date(2024, 1, 3), "open": 86500.0,
         "high": 88000.0, "low": 85500.0, "close": 87000.0,
         "volume": 980_000, "value": 85_260_000_000.0, "source": "test"},
    ])
    store.upsert_ohlcv(df)
    return tmp_path / "test.sqlite"


def test_export_from_sqlite(tmp_path, populated_sqlite):
    duckdb_path = tmp_path / "test.duckdb"
    store = DuckDBStore(duckdb_path)
    store.export_from_sqlite(str(populated_sqlite))
    counts = store.table_counts()
    assert counts["ohlcv_daily"] == 2


def test_export_idempotent(tmp_path, populated_sqlite):
    duckdb_path = tmp_path / "test.duckdb"
    store = DuckDBStore(duckdb_path)
    store.export_from_sqlite(str(populated_sqlite))
    store.export_from_sqlite(str(populated_sqlite))  # second export overwrites cleanly
    counts = store.table_counts()
    assert counts["ohlcv_daily"] == 2


def test_views_created(tmp_path, populated_sqlite):
    duckdb_path = tmp_path / "test.duckdb"
    store = DuckDBStore(duckdb_path)
    store.export_from_sqlite(str(populated_sqlite))
    df = store.query("SELECT * FROM v_ohlcv_clean")
    assert len(df) == 2


def test_relative_sqlite_path_resolved(tmp_path, populated_sqlite, monkeypatch):
    monkeypatch.chdir(tmp_path)
    duckdb_path = tmp_path / "test.duckdb"
    store = DuckDBStore(duckdb_path)
    # Pass a relative path — should resolve to the correct file
    store.export_from_sqlite("test.sqlite")
    counts = store.table_counts()
    assert counts["ohlcv_daily"] == 2
