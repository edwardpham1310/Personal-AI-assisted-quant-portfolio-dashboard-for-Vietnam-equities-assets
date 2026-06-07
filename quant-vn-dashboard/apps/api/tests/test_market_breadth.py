"""Tests for the market breadth / top-movers producer + read routes."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from fastapi.testclient import TestClient

from schemas.market import Quote
from services import market_breadth, market_cache


def _q(
    symbol: str,
    price: float,
    ref: float,
    *,
    volume: float | None = None,
    value: float | None = None,
    ceiling: float | None = None,
    floor: float | None = None,
) -> Quote:
    return Quote(
        symbol=symbol,
        exchange="HOSE",
        price=price,
        reference_price=ref,
        change=price - ref,
        change_pct=(price - ref) / ref,
        volume=volume,
        value=value,
        ceiling_price=ceiling,
        floor_price=floor,
        ts=datetime.now(UTC),
        stale=False,
        source="mock",
    )


# ── Pure-function: breadth ────────────────────────────────────────────────────


def test_compute_breadth_counts_direction() -> None:
    quotes = [
        _q("FPT", 102.0, 100.0),  # up
        _q("MWG", 99.0, 100.0),  # down
        _q("HPG", 100.0, 100.0),  # flat
        _q("VNM", 105.0, 100.0),  # up
    ]
    b = market_breadth.compute_breadth(quotes)
    assert b == {"advancers": 2, "decliners": 1, "unchanged": 1, "ceiling": 0, "floor": 0}


def test_compute_breadth_counts_ceiling_and_floor_only_when_limits_present() -> None:
    quotes = [
        _q("FPT", 107.0, 100.0, ceiling=107.0, floor=93.0),  # at ceiling
        _q("MWG", 93.0, 100.0, ceiling=107.0, floor=93.0),  # at floor
        _q("HPG", 101.0, 100.0),  # no limit fields → not counted at limit
    ]
    b = market_breadth.compute_breadth(quotes)
    assert b["ceiling"] == 1
    assert b["floor"] == 1


def test_compute_breadth_skips_quotes_without_reference() -> None:
    q = Quote(symbol="X", price=10.0, ts=datetime.now(UTC), source="mock")  # no ref/change
    b = market_breadth.compute_breadth([q])
    # Not counted anywhere — no usable direction.
    assert b == {"advancers": 0, "decliners": 0, "unchanged": 0, "ceiling": 0, "floor": 0}


# ── Pure-function: top movers ─────────────────────────────────────────────────


def test_compute_top_movers_ranks_gainers_losers_value_and_volume() -> None:
    quotes = [
        _q("UP1", 110.0, 100.0, volume=2_000.0, value=5_000.0),  # +10%
        _q("UP2", 105.0, 100.0, volume=8_000.0, value=9_000.0),  # +5%
        _q("DN1", 90.0, 100.0, volume=5_000.0, value=1_000.0),  # -10%
    ]
    m = market_breadth.compute_top_movers(quotes)
    assert [r["symbol"] for r in m["gainers"]] == ["UP1", "UP2"]
    assert [r["symbol"] for r in m["losers"]] == ["DN1"]
    # by_value sorts by traded value desc, independent of price move.
    assert [r["symbol"] for r in m["by_value"]] == ["UP2", "UP1", "DN1"]
    assert m["by_value"][0]["value"] == 9_000.0
    # by_volume sorts by raw session volume desc (replaces the old fake spike).
    assert [r["symbol"] for r in m["by_volume"]] == ["UP2", "DN1", "UP1"]
    assert m["by_volume"][0]["volume"] == 8_000.0
    assert "by_volume_spike" not in m


def test_compute_top_movers_by_volume_empty_when_volume_absent() -> None:
    quotes = [_q("UP1", 110.0, 100.0), _q("DN1", 90.0, 100.0)]  # no volume field
    m = market_breadth.compute_top_movers(quotes)
    assert m["by_volume"] == []


def test_compute_top_movers_by_value_empty_when_value_absent() -> None:
    quotes = [_q("UP1", 110.0, 100.0), _q("DN1", 90.0, 100.0)]  # no value field
    m = market_breadth.compute_top_movers(quotes)
    assert m["by_value"] == []
    assert [r["symbol"] for r in m["gainers"]] == ["UP1"]


def test_empty_shapes_have_all_keys() -> None:
    assert set(market_breadth.empty_breadth()) == {
        "advancers",
        "decliners",
        "unchanged",
        "ceiling",
        "floor",
    }
    assert set(market_breadth.empty_top_movers()) == {
        "gainers",
        "losers",
        "by_value",
        "by_volume",
    }


# ── Routes ────────────────────────────────────────────────────────────────────


def test_live_breadth_requires_auth(client: TestClient) -> None:
    assert client.get("/market/live/breadth").status_code == 401
    assert client.get("/market/live/top-movers").status_code == 401


def test_live_breadth_cold_cache_returns_empty_shape(client: TestClient, auth_headers) -> None:
    headers, _ = auth_headers()
    r = client.get("/market/live/breadth", headers=headers)
    assert r.status_code == 200
    body = r.json()
    assert {k: body[k] for k in ("advancers", "decliners", "unchanged", "ceiling", "floor")} == {
        "advancers": 0, "decliners": 0, "unchanged": 0, "ceiling": 0, "floor": 0
    }
    # Honest coverage: default is the polled tracked universe, NOT full-market.
    assert body["coverage"] == "tracked_universe"
    assert body["universe_size"] == 6  # default market_core_symbols


def test_live_top_movers_cold_cache_returns_full_empty_shape(
    client: TestClient, auth_headers
) -> None:
    headers, _ = auth_headers()
    r = client.get("/market/live/top-movers", headers=headers)
    assert r.status_code == 200
    body = r.json()
    # All four keys present so the frontend never indexes undefined.
    assert {k: body[k] for k in ("gainers", "losers", "by_value", "by_volume")} == {
        "gainers": [], "losers": [], "by_value": [], "by_volume": []
    }
    assert body["coverage"] == "tracked_universe"


def test_live_breadth_returns_seeded_payload(client: TestClient, auth_headers, fake_cache) -> None:
    payload = {"advancers": 7, "decliners": 3, "unchanged": 1, "ceiling": 2, "floor": 0}
    asyncio.run(market_cache.set_breadth(fake_cache, payload, ttl_seconds=60))

    headers, _ = auth_headers()
    r = client.get("/market/live/breadth", headers=headers)
    assert r.status_code == 200
    body = r.json()
    assert {k: body[k] for k in payload} == payload
    assert body["coverage"] == "tracked_universe"


def test_live_breadth_full_market_coverage_when_enabled_and_warm(
    client: TestClient, auth_headers, fake_cache, monkeypatch
) -> None:
    monkeypatch.setenv("ENABLE_FULL_MARKET_SCAN", "true")
    from core.config import get_settings

    get_settings.cache_clear()
    asyncio.run(
        market_cache.set_full_scan(
            fake_cache,
            {
                "breadth": {"advancers": 300, "decliners": 250, "unchanged": 40,
                            "ceiling": 9, "floor": 4},
                "top_movers": {"gainers": [], "losers": [], "by_value": [], "by_volume": []},
                "universe_size": 420,
            },
            ttl_seconds=600,
        )
    )
    headers, _ = auth_headers()
    b = client.get("/market/live/breadth", headers=headers).json()
    assert b["coverage"] == "full_market"
    assert b["universe_size"] == 420
    assert b["advancers"] == 300
    m = client.get("/market/live/top-movers", headers=headers).json()
    assert m["coverage"] == "full_market"
    assert m["universe_size"] == 420
