"""Tests for ``/market/live/*`` and the cache-backed quote freshness logic."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from schemas.market import Quote
from services import market_cache


def _seed(fake_cache, quote: Quote, ttl: int = 3600) -> None:
    asyncio.run(market_cache.set_quote(fake_cache, quote, ttl_seconds=ttl))


def _seed_index(fake_cache, code: str, payload: dict, ttl: int = 60) -> None:
    asyncio.run(market_cache.set_index(fake_cache, code, payload, ttl_seconds=ttl))


def test_live_quotes_require_auth(client: TestClient) -> None:
    assert client.get("/market/live/quotes?symbols=FPT").status_code == 401
    assert client.get("/market/live/status").status_code == 401


def test_live_quotes_returns_fresh_quote(client: TestClient, auth_headers, fake_cache) -> None:
    _seed(
        fake_cache,
        Quote(
            symbol="HPG",
            exchange="HOSE",
            price=25_500.0,
            reference_price=25_000.0,
            ts=datetime.now(timezone.utc),
            stale=False,
            source="mock",
        ),
    )

    headers, _ = auth_headers()
    r = client.get("/market/live/quotes?symbols=HPG", headers=headers)
    assert r.status_code == 200
    body = r.json()
    assert body[0]["symbol"] == "HPG"
    assert body[0]["stale"] is False


def test_live_quotes_marks_stale_when_old(client: TestClient, auth_headers, fake_cache) -> None:
    old_ts = datetime.now(timezone.utc) - timedelta(minutes=10)
    _seed(
        fake_cache,
        Quote(
            symbol="FPT",
            exchange="HOSE",
            price=86_500.0,
            ts=old_ts,
            stale=False,
            source="mock",
        ),
    )

    headers, _ = auth_headers()
    r = client.get("/market/live/quotes?symbols=FPT", headers=headers)
    assert r.status_code == 200
    rows = r.json()
    assert len(rows) == 1
    assert rows[0]["stale"] is True


def test_live_quotes_empty_when_cache_cold(client: TestClient, auth_headers) -> None:
    headers, _ = auth_headers()
    r = client.get("/market/live/quotes?symbols=FPT,MWG", headers=headers)
    assert r.status_code == 200
    assert r.json() == []


def test_live_quotes_validates_symbol_format(client: TestClient, auth_headers) -> None:
    headers, _ = auth_headers()
    r = client.get("/market/live/quotes?symbols=FPT,b@d", headers=headers)
    assert r.status_code == 400


def test_live_indices_returns_cache_only(client: TestClient, auth_headers, fake_cache) -> None:
    _seed_index(
        fake_cache,
        "VNINDEX",
        {
            "code": "VNINDEX",
            "close": 1280.0,
            "open": 1278.0,
            "high": 1283.0,
            "low": 1275.0,
            "volume": 1_000_000.0,
            "ts": "2026-05-29T08:00:00+00:00",
        },
    )

    headers, _ = auth_headers()
    r = client.get("/market/live/indices", headers=headers)
    assert r.status_code == 200
    codes = {row["code"] for row in r.json()}
    assert "VNINDEX" in codes


def test_live_status_reports_cache_backend(client: TestClient, auth_headers) -> None:
    headers, _ = auth_headers()
    r = client.get("/market/live/status", headers=headers)
    assert r.status_code == 200
    body = r.json()
    assert body["cache_backend"] == "memory"
    assert body["poller_enabled"] is False
    assert body["poller_running"] is False
    # No poll has run yet — last_poll is None.
    assert body["last_poll"] is None
