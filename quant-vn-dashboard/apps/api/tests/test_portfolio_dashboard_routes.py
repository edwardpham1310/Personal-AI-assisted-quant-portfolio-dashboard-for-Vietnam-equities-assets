"""Tests for GET /portfolio/today-pnl and /portfolio/allocation."""

from __future__ import annotations

import json
from datetime import UTC, datetime

from fastapi.testclient import TestClient

from schemas.market import Quote
from services import market_cache


def _seed_quote(fake_cache, symbol: str, price: float, reference_price: float | None = None) -> None:
    q = Quote(
        symbol=symbol,
        exchange="HOSE",
        price=price,
        reference_price=reference_price,
        ts=datetime.now(UTC),
        source="mock",
    )
    fake_cache._data[market_cache.QUOTE_KEY.format(symbol=symbol)] = (
        json.dumps(q.model_dump(mode="json"), default=str),
        None,
    )


def _add_position(client, headers, symbol, quantity, avg_cost, tag=None) -> None:
    body = {"symbol": symbol, "quantity": quantity, "avg_cost": avg_cost}
    if tag:
        body["strategy_tag"] = tag
    r = client.post("/portfolio/positions", headers=headers, json=body)
    assert r.status_code == 201, r.text


# ── Today PnL ─────────────────────────────────────────────────────────────────


def test_dashboard_routes_require_auth(client: TestClient) -> None:
    assert client.get("/portfolio/today-pnl").status_code == 401
    assert client.get("/portfolio/allocation").status_code == 401


def test_today_pnl_new_user_zero(client: TestClient, auth_headers) -> None:
    headers, _ = auth_headers()
    r = client.get("/portfolio/today-pnl", headers=headers)
    assert r.status_code == 200
    assert r.json()["total_day_pnl"] == 0.0
    assert r.json()["positions"] == []


def test_today_pnl_uses_reference_price(client: TestClient, auth_headers, fake_cache) -> None:
    headers, _ = auth_headers()
    _seed_quote(fake_cache, "FPT", price=95.0, reference_price=90.0)
    _seed_quote(fake_cache, "HPG", price=30.0, reference_price=32.0)
    _add_position(client, headers, "FPT", 100, 80.0)
    _add_position(client, headers, "HPG", 200, 33.0)

    body = client.get("/portfolio/today-pnl", headers=headers).json()
    # FPT: (95-90)*100 = 500 ; HPG: (30-32)*200 = -400 ; total = 100
    assert body["total_day_pnl"] == 100.0
    by_sym = {p["symbol"]: p for p in body["positions"]}
    assert by_sym["FPT"]["day_pnl"] == 500.0
    assert by_sym["HPG"]["day_pnl"] == -400.0


def test_today_pnl_warns_when_reference_missing(client: TestClient, auth_headers, fake_cache) -> None:
    headers, _ = auth_headers()
    _seed_quote(fake_cache, "FPT", price=95.0, reference_price=None)
    _add_position(client, headers, "FPT", 100, 80.0)

    body = client.get("/portfolio/today-pnl", headers=headers).json()
    assert any("reference_price_missing:FPT" in w for w in body["warnings"])
    assert body["positions"][0]["day_pnl"] is None
    assert body["total_day_pnl"] == 0.0


# ── Allocation ────────────────────────────────────────────────────────────────


def test_allocation_new_user_empty(client: TestClient, auth_headers) -> None:
    headers, _ = auth_headers()
    body = client.get("/portfolio/allocation", headers=headers).json()
    assert body["by_strategy_tag"] == []
    assert body["by_symbol"] == []
    assert body["total_market_value"] == 0.0


def test_allocation_by_tag_and_symbol(client: TestClient, auth_headers, fake_cache) -> None:
    headers, _ = auth_headers()
    _seed_quote(fake_cache, "FPT", price=100.0, reference_price=99.0)
    _seed_quote(fake_cache, "HPG", price=50.0, reference_price=50.0)
    _add_position(client, headers, "FPT", 100, 80.0, tag="tech")
    _add_position(client, headers, "HPG", 100, 40.0, tag="steel")

    body = client.get("/portfolio/allocation", headers=headers).json()
    # FPT mv=10000, HPG mv=5000, total=15000
    assert body["total_market_value"] == 15000.0
    tags = {s["label"]: s for s in body["by_strategy_tag"]}
    assert tags["tech"]["value"] == 10000.0
    assert abs(tags["tech"]["weight"] - (10000.0 / 15000.0)) < 1e-6
    syms = {s["label"]: s for s in body["by_symbol"]}
    assert syms["FPT"]["value"] == 10000.0
    assert syms["HPG"]["value"] == 5000.0
