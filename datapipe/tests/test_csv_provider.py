"""Tests for CSV provider contract."""

from __future__ import annotations

import os
import tempfile
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from quant_vn_data.providers.csv_provider import CSVProvider
from quant_vn_data.providers.base import ProviderError


def _write_csv(rows: list[dict], tmp_path: Path, filename="test.csv") -> Path:
    df = pd.DataFrame(rows)
    p = tmp_path / filename
    df.to_csv(p, index=False)
    return p


@pytest.fixture
def sample_csv(tmp_path):
    rows = [
        {"date": "2024-01-02", "symbol": "FPT", "open": 85000, "high": 87000, "low": 83000, "close": 86000, "volume": 1000000},
        {"date": "2024-01-03", "symbol": "FPT", "open": 86000, "high": 88000, "low": 85000, "close": 87000, "volume": 900000},
        {"date": "2024-01-04", "symbol": "MWG", "open": 45000, "high": 46000, "low": 44000, "close": 45500, "volume": 500000},
    ]
    return _write_csv(rows, tmp_path)


def test_get_daily_ohlcv_filters_by_symbol(sample_csv):
    provider = CSVProvider(sample_csv)
    df = provider.get_daily_ohlcv("FPT", "2024-01-01", "2024-12-31")
    assert len(df) == 2
    assert all(df["symbol"].str.upper() == "FPT")


def test_get_daily_ohlcv_date_range(sample_csv):
    provider = CSVProvider(sample_csv)
    df = provider.get_daily_ohlcv("FPT", "2024-01-03", "2024-12-31")
    assert len(df) == 1


def test_missing_file_raises_provider_error(tmp_path):
    provider = CSVProvider(tmp_path / "nonexistent.csv")
    with pytest.raises(ProviderError):
        provider.get_daily_ohlcv("FPT", "2024-01-01", "2024-12-31")


def test_column_aliases(tmp_path):
    rows = [{"Date": "2024-01-02", "ticker": "VCB", "Open": 80000, "High": 82000, "Low": 79000, "Close": 81000, "Volume": 500000}]
    path = _write_csv(rows, tmp_path)
    provider = CSVProvider(path)
    df = provider.get_daily_ohlcv("VCB", "2024-01-01", "2024-12-31")
    assert not df.empty
    assert "close" in df.columns or "Close" in df.columns


def test_get_symbols(sample_csv):
    provider = CSVProvider(sample_csv)
    df = provider.get_symbols()
    symbols = df["symbol"].tolist()
    assert "FPT" in symbols
    assert "MWG" in symbols
