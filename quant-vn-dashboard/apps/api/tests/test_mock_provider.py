"""Mock provider unit tests."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from providers.market_data import MockMarketDataProvider, ProviderError


@pytest.mark.asyncio
async def test_mock_securities_lists_known_symbols() -> None:
    provider = MockMarketDataProvider()
    rows = await provider.get_securities()
    symbols = {s.symbol for s in rows}
    assert {"FPT", "MWG", "HPG", "VNM"} <= symbols


@pytest.mark.asyncio
async def test_mock_security_details_for_known_symbol() -> None:
    provider = MockMarketDataProvider()
    sec = await provider.get_security_details("fpt")
    assert sec.symbol == "FPT"
    assert sec.exchange == "HOSE"
    assert sec.lot_size == 100


@pytest.mark.asyncio
async def test_mock_unknown_symbol_raises_404() -> None:
    provider = MockMarketDataProvider()
    with pytest.raises(ProviderError) as exc_info:
        await provider.get_security_details("UNKNOWN")
    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_mock_index_components_returns_known_index() -> None:
    provider = MockMarketDataProvider()
    comps = await provider.get_index_components("VN30")
    assert "FPT" in comps
    assert "HPG" in comps


@pytest.mark.asyncio
async def test_mock_daily_ohlcv_is_deterministic_and_skips_weekends() -> None:
    provider = MockMarketDataProvider()
    # 2026-05-25 is a Monday; range covers exactly 5 weekdays + 2 weekend days.
    start = date(2026, 5, 25)
    end = start + timedelta(days=6)
    bars1 = await provider.get_daily_ohlcv("FPT", start, end)
    bars2 = await provider.get_daily_ohlcv("FPT", start, end)
    assert len(bars1) == 5  # Mon–Fri only
    # Same query → same data.
    assert [b.model_dump() for b in bars1] == [b.model_dump() for b in bars2]
    for bar in bars1:
        assert bar.low <= bar.close <= bar.high
        assert bar.volume > 0


@pytest.mark.asyncio
async def test_mock_intraday_ohlcv_respects_interval() -> None:
    provider = MockMarketDataProvider()
    day = date(2026, 5, 25)  # Monday
    bars_5m = await provider.get_intraday_ohlcv("MWG", day, day, "5m")
    bars_15m = await provider.get_intraday_ohlcv("MWG", day, day, "15m")
    assert len(bars_5m) > 0
    assert len(bars_5m) > len(bars_15m)
    # The mock session is 02:00→08:00 UTC inclusive on both ends:
    #   5m bars = 6 * 60 / 5 + 1 = 73
    #   15m bars = 6 * 60 / 15 + 1 = 25
    # So len(5m) = 3 * (len(15m) - 1) + 1 — the loose bound below tolerates
    # the off-by-one introduced by inclusive endpoints.
    assert len(bars_5m) >= 3 * (len(bars_15m) - 1) + 1


@pytest.mark.asyncio
async def test_mock_intraday_rejects_bad_interval() -> None:
    provider = MockMarketDataProvider()
    day = date(2026, 5, 25)
    with pytest.raises(ProviderError) as exc:
        await provider.get_intraday_ohlcv("FPT", day, day, "7m")  # type: ignore[arg-type]
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_mock_latest_quotes_marks_source() -> None:
    provider = MockMarketDataProvider()
    quotes = await provider.get_latest_quotes(["FPT", "VNM", "UNKNOWN"])
    # Unknown silently dropped.
    assert {q.symbol for q in quotes} == {"FPT", "VNM"}
    for q in quotes:
        assert q.source == "mock"
        assert q.price > 0
        assert q.reference_price is not None
        assert q.stale is False


@pytest.mark.asyncio
async def test_mock_status() -> None:
    provider = MockMarketDataProvider()
    s = await provider.status()
    assert s.name == "mock"
    assert s.mock is True
    assert s.ready is True
