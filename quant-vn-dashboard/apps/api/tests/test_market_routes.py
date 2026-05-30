"""Market route tests — exercised through the mock provider injected by conftest."""

from __future__ import annotations

from datetime import date, timedelta

from fastapi.testclient import TestClient


def test_market_requires_auth(client: TestClient) -> None:
    assert client.get("/market/securities").status_code == 401
    assert client.get("/market/quotes?symbols=FPT").status_code == 401


def test_status_reports_mock(client: TestClient, auth_headers) -> None:
    headers, _ = auth_headers()
    r = client.get("/market/status", headers=headers)
    assert r.status_code == 200
    body = r.json()
    assert body["name"] == "mock"
    assert body["mock"] is True
    assert body["ready"] is True


def test_securities_list(client: TestClient, auth_headers) -> None:
    headers, _ = auth_headers()
    r = client.get("/market/securities?exchange=HOSE", headers=headers)
    assert r.status_code == 200
    rows = r.json()
    syms = {row["symbol"] for row in rows}
    assert "FPT" in syms


def test_securities_invalid_exchange(client: TestClient, auth_headers) -> None:
    headers, _ = auth_headers()
    r = client.get("/market/securities?exchange=NYSE", headers=headers)
    assert r.status_code == 400


def test_security_details_known_symbol(client: TestClient, auth_headers) -> None:
    headers, _ = auth_headers()
    r = client.get("/market/securities/fpt", headers=headers)  # lowercase intentionally
    assert r.status_code == 200
    body = r.json()
    assert body["symbol"] == "FPT"
    assert body["lot_size"] == 100


def test_indices_and_components(client: TestClient, auth_headers) -> None:
    headers, _ = auth_headers()
    r = client.get("/market/indices", headers=headers)
    assert r.status_code == 200
    codes = {row["code"] for row in r.json()}
    assert "VNINDEX" in codes
    assert "VN30" in codes

    r = client.get("/market/index-components/VN30", headers=headers)
    assert r.status_code == 200
    members = r.json()
    assert "FPT" in members


def test_quotes_validates_symbol_count(client: TestClient, auth_headers) -> None:
    headers, _ = auth_headers()
    symbols = ",".join(f"SYM{i}" for i in range(60))
    r = client.get(f"/market/quotes?symbols={symbols}", headers=headers)
    assert r.status_code == 400
    assert "Max" in r.json()["detail"]


def test_quotes_validates_symbol_format(client: TestClient, auth_headers) -> None:
    headers, _ = auth_headers()
    r = client.get("/market/quotes?symbols=FPT,b@d", headers=headers)
    assert r.status_code == 400
    assert "Invalid symbol" in r.json()["detail"]


def test_quotes_empty_list_rejected(client: TestClient, auth_headers) -> None:
    headers, _ = auth_headers()
    r = client.get("/market/quotes?symbols=", headers=headers)
    assert r.status_code == 400


def test_quotes_returns_provider_timestamp(client: TestClient, auth_headers) -> None:
    headers, _ = auth_headers()
    r = client.get("/market/quotes?symbols=FPT,VNM", headers=headers)
    assert r.status_code == 200
    rows = r.json()
    assert len(rows) == 2
    for row in rows:
        assert row["source"] == "mock"
        assert "ts" in row
        assert "stale" in row


def test_daily_ohlcv_rejects_inverted_range(client: TestClient, auth_headers) -> None:
    headers, _ = auth_headers()
    r = client.get(
        "/market/ohlcv/daily/FPT?start=2026-05-10&end=2026-05-01",
        headers=headers,
    )
    assert r.status_code == 400


def test_daily_ohlcv_rejects_future_end(client: TestClient, auth_headers) -> None:
    headers, _ = auth_headers()
    future = date.today() + timedelta(days=30)
    r = client.get(
        f"/market/ohlcv/daily/FPT?start=2026-01-01&end={future.isoformat()}",
        headers=headers,
    )
    assert r.status_code == 400


def test_daily_ohlcv_rejects_oversized_range(client: TestClient, auth_headers) -> None:
    headers, _ = auth_headers()
    today = date.today()
    r = client.get(
        f"/market/ohlcv/daily/FPT?start={(today - timedelta(days=500)).isoformat()}&end={today.isoformat()}",
        headers=headers,
    )
    assert r.status_code == 400
    assert "max" in r.json()["detail"].lower()


def test_daily_ohlcv_happy_path(client: TestClient, auth_headers) -> None:
    headers, _ = auth_headers()
    end = date(2026, 5, 25)
    start = end - timedelta(days=14)
    r = client.get(
        f"/market/ohlcv/daily/FPT?start={start.isoformat()}&end={end.isoformat()}",
        headers=headers,
    )
    assert r.status_code == 200
    bars = r.json()
    assert all(b["symbol"] == "FPT" for b in bars)
    assert all(b["low"] <= b["close"] <= b["high"] for b in bars)


def test_intraday_ohlcv_rejects_bad_interval(client: TestClient, auth_headers) -> None:
    headers, _ = auth_headers()
    r = client.get(
        "/market/ohlcv/intraday/FPT?start=2026-05-25&end=2026-05-25&interval=7m",
        headers=headers,
    )
    assert r.status_code == 422  # FastAPI rejects via Literal type
