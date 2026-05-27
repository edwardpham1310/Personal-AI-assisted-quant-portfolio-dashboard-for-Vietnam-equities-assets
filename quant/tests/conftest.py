"""Shared pytest fixtures for quant-vn tests."""

from __future__ import annotations

import datetime

import numpy as np
import pandas as pd
import pytest


@pytest.fixture
def sample_prices() -> pd.DataFrame:
    """
    Synthetic daily OHLCV data for 500 trading days.
    Uses a deterministic random walk so tests are reproducible.
    """
    rng = np.random.default_rng(42)
    n = 500
    dates = pd.date_range(start="2020-01-02", periods=n, freq="B")

    close = 100.0 * np.exp(np.cumsum(rng.normal(0.0004, 0.015, n)))
    high = close * (1 + rng.uniform(0.001, 0.02, n))
    low = close * (1 - rng.uniform(0.001, 0.02, n))
    open_ = low + rng.uniform(0, 1, n) * (high - low)
    volume = rng.integers(100_000, 5_000_000, n).astype(int)

    return pd.DataFrame({
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
        "volume": volume,
    }, index=dates)


@pytest.fixture
def known_prices() -> pd.DataFrame:
    """
    Prices with a known pattern for correctness testing.
    Days 0-9: price=100 (flat), Days 10-19: price rises to 200, Days 20-29: price falls back.
    Used to verify exact trade dates and PnL.
    """
    dates = pd.date_range(start="2020-01-02", periods=30, freq="B")
    close = [100.0] * 10 + list(np.linspace(100, 200, 10)) + list(np.linspace(200, 100, 10))
    prices = pd.DataFrame({
        "open": close,
        "high": [c * 1.01 for c in close],
        "low": [c * 0.99 for c in close],
        "close": close,
        "volume": [1_000_000] * 30,
    }, index=dates)
    return prices


@pytest.fixture
def tmp_db(tmp_path):
    """Temporary SQLite database for storage tests."""
    from quant_vn.data.storage import Database
    db = Database(url=f"sqlite:///{tmp_path}/test.db")
    db.init_db()
    return db
