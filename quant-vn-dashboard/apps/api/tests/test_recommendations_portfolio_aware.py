"""Feature 7 — portfolio-aware recommendation enrichment."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from schemas.market import OHLCVBar, Quote
from schemas.portfolio import EnrichedPosition
from services import market_cache
from services.recommendation_engine import CONCENTRATION_WARN_PCT, generate_recommendation


def _bars(n: int = 260, start_price: float = 50.0) -> list[OHLCVBar]:
    start = datetime(2025, 1, 2, tzinfo=UTC)
    out = []
    for i in range(n):
        c = start_price + i * 0.05  # gentle uptrend, clears MA200
        out.append(
            OHLCVBar(
                symbol="TEST", ts=start + timedelta(days=i),
                open=c, high=c * 1.02, low=c * 0.98, close=c,
                volume=3_000_000_000.0 * (1.0 + 0.4 * ((i % 5) - 2) / 2.0),
                value=c * 3_000_000_000.0,
            )
        )
    return out


def _rec(positions):
    return generate_recommendation(
        symbol="TEST", profile="short_aggressive", horizon="SHORT_2W",
        bars=_bars(), latest_quote=None, vnindex_bars=None,
        portfolio_positions=positions, total_equity=1_000_000.0,
    )


# ── engine: held facts ────────────────────────────────────────────────────────


def test_engine_marks_held_with_concentration() -> None:
    rec = _rec([
        {"symbol": "TEST", "weight": 0.20, "quantity": 1000, "avg_cost": 50.0,
         "unrealized_pnl_pct": 0.1},
    ])
    assert rec.is_held is True
    assert rec.held_weight_pct == 20.0
    assert rec.held_quantity == 1000.0
    assert rec.held_avg_cost == 50.0
    assert rec.held_unrealized_pct == 0.1
    assert rec.portfolio_note and "concentration" in rec.portfolio_note.lower()
    assert "portfolio_concentration" in rec.warnings
    assert CONCENTRATION_WARN_PCT <= 20.0


def test_engine_held_below_concentration_has_no_warning() -> None:
    rec = _rec([{"symbol": "TEST", "weight": 0.05, "quantity": 100, "avg_cost": 50.0}])
    assert rec.is_held is True
    assert rec.held_weight_pct == 5.0
    assert "portfolio_concentration" not in rec.warnings
    assert rec.portfolio_note == "Already held (5.0% of holdings)."


def test_engine_not_held_when_symbol_absent() -> None:
    rec = _rec([{"symbol": "OTHER", "weight": 0.30, "quantity": 100, "avg_cost": 10.0}])
    assert rec.is_held is False
    assert rec.held_weight_pct is None
    assert rec.portfolio_note is None


def test_engine_no_portfolio_context() -> None:
    rec = _rec(None)
    assert rec.is_held is False
    assert rec.held_weight_pct is None


def test_engine_reads_enriched_position_objects() -> None:
    pos = EnrichedPosition(
        id="p1", account_id="a1", symbol="TEST", exchange="HOSE",
        quantity=500, avg_cost=48.0, weight=0.18, unrealized_pnl_pct=0.05,
    )
    rec = _rec([pos])
    assert rec.is_held is True
    assert rec.held_weight_pct == 18.0
    assert rec.held_quantity == 500.0


# ── route: enrichment surfaces on /symbol ─────────────────────────────────────


def test_symbol_route_surfaces_held_facts(
    client: TestClient, auth_headers, fake_cache
) -> None:
    headers, _ = auth_headers()
    # Create a holding via the portfolio API (creates the account too).
    r = client.post(
        "/portfolio/positions",
        headers=headers,
        json={"symbol": "FPT", "quantity": 100, "avg_cost": 70.0},
    )
    assert r.status_code == 201, r.text
    # Seed a quote so the valuation service can weight the (single) position.
    q = Quote(
        symbol="FPT", exchange="HOSE", price=80.0, reference_price=80.0,
        change=0, change_pct=0, volume=1000, value=80_000,
        ts=datetime.now(UTC), stale=False, source="test",
    )
    asyncio.run(market_cache.set_quote(fake_cache, q, ttl_seconds=300))

    body = client.get("/recommendations/symbol/FPT", headers=headers).json()
    assert body["is_held"] is True
    # Single holding → 100% of holdings → concentration flagged.
    assert body["held_weight_pct"] == 100.0
    assert "portfolio_concentration" in body["warnings"]
    assert body["held_quantity"] == 100.0


def test_symbol_route_not_held_when_no_portfolio(client: TestClient, auth_headers) -> None:
    headers, _ = auth_headers()
    body = client.get("/recommendations/symbol/FPT", headers=headers).json()
    assert body["is_held"] is False
    assert body["held_weight_pct"] is None
