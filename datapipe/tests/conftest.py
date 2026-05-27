"""Shared fixtures for quant-vn-data tests."""

from __future__ import annotations

import pytest
import pandas as pd
from datetime import date


@pytest.fixture
def sample_ohlcv_df():
    """Valid OHLCV DataFrame for FPT over 3 days."""
    return pd.DataFrame([
        {"symbol": "FPT", "trading_date": date(2024, 1, 2), "open": 85000.0, "high": 87000.0,
         "low": 84000.0, "close": 86500.0, "volume": 1_200_000, "value": 103_800_000_000.0,
         "source": "test", "quality_status": "OK"},
        {"symbol": "FPT", "trading_date": date(2024, 1, 3), "open": 86500.0, "high": 88000.0,
         "low": 85500.0, "close": 87000.0, "volume": 980_000, "value": 85_260_000_000.0,
         "source": "test", "quality_status": "OK"},
        {"symbol": "FPT", "trading_date": date(2024, 1, 4), "open": 87000.0, "high": 89000.0,
         "low": 86000.0, "close": 88500.0, "volume": 1_500_000, "value": 132_750_000_000.0,
         "source": "test", "quality_status": "OK"},
    ])


@pytest.fixture
def in_memory_db(tmp_path):
    """Isolated in-memory SQLite database for tests."""
    from quant_vn_data.storage.database import Database
    db = Database(f"sqlite:///{tmp_path}/test.sqlite")
    db.create_all()
    return db
