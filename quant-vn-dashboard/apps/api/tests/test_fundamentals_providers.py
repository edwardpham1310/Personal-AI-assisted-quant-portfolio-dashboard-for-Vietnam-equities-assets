"""Tests for the FundamentalDataProvider abstraction and the Null/CSV
implementations. The DB provider needs a live Supabase fake and is
covered indirectly by the recommendation-route tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from providers.fundamentals.csv_provider import CSVFundamentalProvider
from providers.fundamentals.null_provider import NullFundamentalProvider
from schemas.fundamentals import compute_data_status, Fundamentals


# ── NullFundamentalProvider ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_null_provider_returns_none_for_every_symbol() -> None:
    provider = NullFundamentalProvider()
    assert await provider.get_fundamentals("FPT") is None
    batch = await provider.get_many(["FPT", "MWG", "HPG"])
    assert batch == {"FPT": None, "MWG": None, "HPG": None}


@pytest.mark.asyncio
async def test_null_provider_status_signals_not_implemented() -> None:
    status = await NullFundamentalProvider().status()
    assert status.status_code == "NOT_IMPLEMENTED"
    assert status.symbols_covered == 0


# ── CSVFundamentalProvider ─────────────────────────────────────────────────


CSV_SAMPLE = """symbol,market_cap,listed_share,roe,net_profit_q1,net_profit_q2,net_profit_q3,net_profit_q4,audit_opinion,fiscal_period,is_vn30,is_vn100,fundamentals_as_of
FPT,150000000000000,1234567890,20.5,1000000000,1100000000,1200000000,1300000000,UNQUALIFIED,2025-Q4,true,true,2025-12-31
MWG,90000000000000,1500000000,15.0,800000000,850000000,900000000,950000000,Chấp nhận toàn phần,2025-Q4,true,true,2025-12-31
PENNY,500000000000,,4.0,-50000000,10000000,5000000,20000000,QUALIFIED,2025-Q4,false,false,2025-12-31
SPARSE,,,,,,,,,,,
"""


@pytest.fixture()
def csv_path(tmp_path: Path) -> Path:
    p = tmp_path / "fundamentals.csv"
    p.write_text(CSV_SAMPLE, encoding="utf-8")
    return p


@pytest.mark.asyncio
async def test_csv_loads_known_symbol(csv_path: Path) -> None:
    provider = CSVFundamentalProvider(csv_path)
    fpt = await provider.get_fundamentals("fpt")
    assert fpt is not None
    assert fpt.symbol == "FPT"
    assert fpt.market_cap == 150_000_000_000_000
    assert fpt.roe == 20.5
    assert fpt.net_profit_last_4_quarters == [1e9, 1.1e9, 1.2e9, 1.3e9]
    assert fpt.audit_opinion == "UNQUALIFIED"
    assert fpt.is_vn100 is True


@pytest.mark.asyncio
async def test_csv_normalises_vietnamese_audit_opinion(csv_path: Path) -> None:
    provider = CSVFundamentalProvider(csv_path)
    mwg = await provider.get_fundamentals("MWG")
    assert mwg is not None
    assert mwg.audit_opinion == "UNQUALIFIED"  # normalised from VN text


@pytest.mark.asyncio
async def test_csv_returns_none_for_unknown_symbol(csv_path: Path) -> None:
    provider = CSVFundamentalProvider(csv_path)
    assert await provider.get_fundamentals("UNKNOWN") is None


@pytest.mark.asyncio
async def test_csv_treats_blank_numeric_as_none(csv_path: Path) -> None:
    provider = CSVFundamentalProvider(csv_path)
    sparse = await provider.get_fundamentals("SPARSE")
    assert sparse is not None
    assert sparse.market_cap is None
    assert sparse.roe is None


@pytest.mark.asyncio
async def test_csv_partial_quarterly_profit_becomes_none(csv_path: Path) -> None:
    """net_profit_last_4_quarters requires exactly 4 values — partial rows return None."""
    # PENNY row has 4 values so it gets a list; SPARSE has 0 so None.
    provider = CSVFundamentalProvider(csv_path)
    penny = await provider.get_fundamentals("PENNY")
    assert penny is not None
    assert penny.net_profit_last_4_quarters is not None
    assert len(penny.net_profit_last_4_quarters) == 4
    sparse = await provider.get_fundamentals("SPARSE")
    assert sparse is not None
    assert sparse.net_profit_last_4_quarters is None


@pytest.mark.asyncio
async def test_csv_status_reports_symbols_covered(csv_path: Path) -> None:
    provider = CSVFundamentalProvider(csv_path)
    await provider.get_fundamentals("FPT")  # force load
    status = await provider.status()
    assert status.status_code == "CONNECTED"
    assert status.symbols_covered == 4


@pytest.mark.asyncio
async def test_csv_missing_file_reports_config_missing(tmp_path: Path) -> None:
    provider = CSVFundamentalProvider(tmp_path / "does-not-exist.csv")
    status = await provider.status()
    assert status.status_code == "CONFIG_MISSING"
    assert status.last_error is not None
    assert "not found" in status.last_error.lower()


# ── compute_data_status helper ─────────────────────────────────────────────


def test_compute_data_status_missing_when_none() -> None:
    assert compute_data_status(None) == "FUNDAMENTAL_DATA_MISSING"


def test_compute_data_status_partial_when_one_field() -> None:
    f = Fundamentals(symbol="X", roe=15.0)
    assert compute_data_status(f) == "FUNDAMENTAL_DATA_PARTIAL"


def test_compute_data_status_available_when_all_gate_fields_present() -> None:
    f = Fundamentals(
        symbol="X",
        market_cap=1e12,
        roe=15.0,
        net_profit_last_4_quarters=[1e9] * 4,
        audit_opinion="UNQUALIFIED",
    )
    assert compute_data_status(f) == "FUNDAMENTAL_DATA_AVAILABLE"
