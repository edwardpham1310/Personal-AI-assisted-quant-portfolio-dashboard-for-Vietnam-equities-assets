"""Feature 6 — alerts CRUD + evaluation + watchlist-scoped alerts."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from fastapi.testclient import TestClient

from schemas.market import Quote
from services import alerts as alert_eval
from services import market_cache


def _seed_quote(cache, symbol: str, price: float, *, change_pct: float = 0.0, stale=False) -> None:
    q = Quote(
        symbol=symbol, exchange="HOSE", price=price, reference_price=price,
        change=0, change_pct=change_pct, volume=1000, value=price * 1000,
        ts=datetime.now(UTC), stale=stale, source="test",
    )
    asyncio.run(market_cache.set_quote(cache, q, ttl_seconds=300))


def _make_quote(price: float, change_pct: float = 0.0) -> Quote:
    return Quote(
        symbol="FPT", exchange="HOSE", price=price, reference_price=price,
        change=0, change_pct=change_pct, volume=1, value=price,
        ts=datetime.now(UTC), stale=False, source="test",
    )


# ── pure evaluation ───────────────────────────────────────────────────────────


def test_evaluate_price_conditions() -> None:
    q = _make_quote(100.0)
    assert alert_eval.evaluate("price_above", 90, q) is True
    assert alert_eval.evaluate("price_above", 110, q) is False
    assert alert_eval.evaluate("price_below", 110, q) is True
    assert alert_eval.evaluate("price_below", 90, q) is False


def test_evaluate_pct_conditions() -> None:
    q = _make_quote(100.0, change_pct=0.03)
    assert alert_eval.evaluate("pct_change_above", 0.02, q) is True
    assert alert_eval.evaluate("pct_change_above", 0.05, q) is False
    assert alert_eval.evaluate("pct_change_below", 0.05, q) is True


def test_evaluate_unknown_field_returns_none() -> None:
    q = Quote(symbol="FPT", price=100, ts=datetime.now(UTC), source="t")
    assert alert_eval.evaluate("pct_change_above", 0.01, q) is None  # change_pct missing


# ── auth ──────────────────────────────────────────────────────────────────────


def test_alerts_require_auth(client: TestClient) -> None:
    assert client.get("/alerts").status_code == 401
    assert client.post("/alerts", json={"symbol": "FPT", "condition": "price_above", "threshold": 1}).status_code == 401


# ── CRUD ──────────────────────────────────────────────────────────────────────


def _create(client, headers, **over) -> dict:
    body = {"symbol": "fpt", "condition": "price_above", "threshold": 90.0}
    body.update(over)
    r = client.post("/alerts", headers=headers, json=body)
    assert r.status_code == 201, r.text
    return r.json()


def test_create_uppercases_symbol(client: TestClient, auth_headers) -> None:
    headers, uid = auth_headers()
    a = _create(client, headers)
    assert a["symbol"] == "FPT"
    assert a["user_id"] == uid
    assert a["is_active"] is True


def test_create_rejects_invalid_symbol(client: TestClient, auth_headers) -> None:
    headers, _ = auth_headers()
    r = client.post("/alerts", headers=headers, json={"symbol": "!@#", "condition": "price_above", "threshold": 1})
    assert r.status_code == 400


def test_create_rejects_non_numeric_threshold(client: TestClient, auth_headers) -> None:
    headers, _ = auth_headers()
    r = client.post(
        "/alerts", headers=headers,
        json={"symbol": "FPT", "condition": "price_above", "threshold": "abc"},
    )
    assert r.status_code == 422


def test_create_rejects_unknown_condition(client: TestClient, auth_headers) -> None:
    headers, _ = auth_headers()
    r = client.post(
        "/alerts", headers=headers,
        json={"symbol": "FPT", "condition": "moon_above", "threshold": 1},
    )
    assert r.status_code == 422


def test_patch_toggles_active(client: TestClient, auth_headers) -> None:
    headers, _ = auth_headers()
    a = _create(client, headers)
    r = client.patch(f"/alerts/{a['id']}", headers=headers, json={"is_active": False})
    assert r.status_code == 200
    assert r.json()["is_active"] is False


def test_patch_empty_payload_400(client: TestClient, auth_headers) -> None:
    headers, _ = auth_headers()
    a = _create(client, headers)
    assert client.patch(f"/alerts/{a['id']}", headers=headers, json={}).status_code == 400


def test_patch_not_owned_404(client: TestClient, auth_headers) -> None:
    headers_a, _ = auth_headers()
    a = _create(client, headers_a)
    headers_b, _ = auth_headers()
    assert client.patch(f"/alerts/{a['id']}", headers=headers_b, json={"threshold": 5}).status_code == 404


def test_delete_alert(client: TestClient, auth_headers) -> None:
    headers, _ = auth_headers()
    a = _create(client, headers)
    assert client.delete(f"/alerts/{a['id']}", headers=headers).status_code == 204
    assert client.delete(f"/alerts/{a['id']}", headers=headers).status_code == 404


def test_list_is_user_scoped(client: TestClient, auth_headers) -> None:
    headers_a, _ = auth_headers()
    _create(client, headers_a)
    headers_b, _ = auth_headers()
    assert client.get("/alerts", headers=headers_b).json()["alerts"] == []


# ── evaluation on read ────────────────────────────────────────────────────────


def test_list_evaluates_against_quote(client: TestClient, auth_headers, fake_cache) -> None:
    headers, _ = auth_headers()
    _create(client, headers, symbol="FPT", condition="price_above", threshold=90.0)
    _seed_quote(fake_cache, "FPT", 100.0)
    body = client.get("/alerts", headers=headers).json()
    assert body["count"] == 1
    a = body["alerts"][0]
    assert a["evaluated"] is True
    assert a["currently_triggered"] is True
    assert a["observed_price"] == 100.0
    assert body["triggered_count"] == 1
    assert "no orders" in body["disclaimer"].lower()


def test_list_unevaluated_when_quote_cold(client: TestClient, auth_headers) -> None:
    headers, _ = auth_headers()
    _create(client, headers, symbol="ZZZ", condition="price_above", threshold=1.0)
    a = client.get("/alerts", headers=headers).json()["alerts"][0]
    assert a["evaluated"] is False
    assert a["currently_triggered"] is None


def test_active_only_filter(client: TestClient, auth_headers) -> None:
    headers, _ = auth_headers()
    a = _create(client, headers)
    client.patch(f"/alerts/{a['id']}", headers=headers, json={"is_active": False})
    assert client.get("/alerts?active_only=true", headers=headers).json()["count"] == 0
    assert client.get("/alerts", headers=headers).json()["count"] == 1


# ── watchlist-scoped alerts ───────────────────────────────────────────────────


def test_watchlist_alerts_filters_by_symbols(
    client: TestClient, auth_headers, fake_db, fake_cache
) -> None:
    headers, uid = auth_headers()
    wl = client.post("/watchlists", headers=headers, json={"name": "W"}).json()
    client.post(f"/watchlists/{wl['id']}/symbols", headers=headers, json={"symbol": "FPT"})
    _create(client, headers, symbol="FPT", condition="price_below", threshold=200.0)
    _create(client, headers, symbol="MWG", condition="price_above", threshold=1.0)  # not in WL
    _seed_quote(fake_cache, "FPT", 100.0)

    r = client.get(f"/watchlists/{wl['id']}/alerts", headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert [a["symbol"] for a in body["alerts"]] == ["FPT"]
    assert body["alerts"][0]["currently_triggered"] is True


def test_watchlist_alerts_not_owned_404(client: TestClient, auth_headers) -> None:
    headers_a, _ = auth_headers()
    wl = client.post("/watchlists", headers=headers_a, json={"name": "A"}).json()
    headers_b, _ = auth_headers()
    assert client.get(f"/watchlists/{wl['id']}/alerts", headers=headers_b).status_code == 404
