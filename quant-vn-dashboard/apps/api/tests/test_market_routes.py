"""Market route tests — exercised through the mock provider injected by conftest."""

from __future__ import annotations

from datetime import UTC, date, timedelta

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
    # Use UTC date to match the route's own clock — local + UTC can diverge
    # around midnight, which would trip the "end cannot be in the future"
    # check before the max-days check we want to assert against.
    from datetime import datetime as _dt
    today = _dt.now(UTC).date()
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


# ── Phase 2 chart module ────────────────────────────────────────────────────


def test_candles_requires_auth(client: TestClient) -> None:
    assert client.get("/market/candles/FPT").status_code == 401


def test_candles_daily_returns_normalised_shape(
    client: TestClient, auth_headers
) -> None:
    headers, _ = auth_headers()
    r = client.get(
        "/market/candles/FPT?timeframe=1d&range=1m", headers=headers
    )
    assert r.status_code == 200, r.text
    rows = r.json()
    assert isinstance(rows, list)
    if rows:
        c = rows[0]
        for key in (
            "symbol",
            "timeframe",
            "timestamp",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "source",
            "is_realtime",
            "is_stale",
        ):
            assert key in c, f"missing key: {key}"
        assert c["timeframe"] == "1d"
        assert c["is_realtime"] is False
        assert c["source"] in {"SSI", "MOCK"}


def test_candles_intraday_15m(client: TestClient, auth_headers) -> None:
    headers, _ = auth_headers()
    r = client.get(
        "/market/candles/FPT?timeframe=15m&range=5d", headers=headers
    )
    assert r.status_code == 200, r.text
    rows = r.json()
    if rows:
        assert rows[0]["timeframe"] == "15m"
        assert rows[0]["is_realtime"] is True


def test_candles_rejects_unsupported_timeframe(
    client: TestClient, auth_headers
) -> None:
    headers, _ = auth_headers()
    r = client.get(
        "/market/candles/FPT?timeframe=7m&range=1m", headers=headers
    )
    assert r.status_code in (400, 422)


def test_candles_rejects_unsupported_range(
    client: TestClient, auth_headers
) -> None:
    headers, _ = auth_headers()
    r = client.get(
        "/market/candles/FPT?timeframe=1d&range=2y", headers=headers
    )
    assert r.status_code == 400


def test_candles_rejects_bad_symbol(client: TestClient, auth_headers) -> None:
    headers, _ = auth_headers()
    r = client.get(
        "/market/candles/INVALID!SYM?timeframe=1d&range=1m", headers=headers
    )
    assert r.status_code == 400


def test_symbol_detail_requires_auth(client: TestClient) -> None:
    assert client.get("/market/symbol-detail/FPT").status_code == 401


def test_symbol_detail_returns_aggregator_shape(
    client: TestClient, auth_headers
) -> None:
    headers, _ = auth_headers()
    r = client.get("/market/symbol-detail/FPT", headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    for key in (
        "security",
        "quote",
        "intraday",
        "daily",
        "provider_status",
        "freshness",
        "warnings",
        "disclaimer",
    ):
        assert key in body, f"missing key: {key}"
    assert body["security"]["symbol"] == "FPT"
    assert isinstance(body["intraday"], list)
    assert isinstance(body["daily"], list)
    # Provider status code must be one of the Phase 2 codes.
    assert body["provider_status"]["status_code"] in {
        "CONNECTED", "READY",  # CONNECTED preferred; READY kept for back-compat
        "CONFIG_MISSING", "AUTH_FAILED", "RATE_LIMITED",
        "ERROR", "PROVIDER_ERROR",  # ERROR preferred; PROVIDER_ERROR kept for back-compat
        "STALE",
    }
    # Disclaimer must include the research-only language.
    assert "research" in body["disclaimer"].lower()


def test_symbol_detail_quote_carries_ceiling_floor_if_provided(
    client: TestClient, auth_headers
) -> None:
    """The quote section of the aggregator must use the LatestQuote schema
    which carries optional ceiling / floor / value fields."""
    headers, _ = auth_headers()
    r = client.get("/market/symbol-detail/FPT", headers=headers)
    assert r.status_code == 200
    body = r.json()
    q = body.get("quote")
    if q is not None:
        # Fields must be present in the schema even if values are null.
        for key in (
            "last_price",
            "change",
            "change_pct",
            "reference_price",
            "ceiling_price",
            "floor_price",
            "volume",
            "value",
            "provider_timestamp",
            "received_at",
            "is_stale",
            "source",
        ):
            assert key in q, f"missing quote key: {key}"
        assert q["source"] in {"SSI", "MOCK"}


def test_symbol_detail_unknown_symbol_still_returns_shape(
    client: TestClient, auth_headers
) -> None:
    """Aggregator must be defensive — never raise on partial provider
    failure. Unknown symbol → empty intraday/daily, warnings list grows.
    """
    headers, _ = auth_headers()
    r = client.get("/market/symbol-detail/UNKNOWN", headers=headers)
    # Even when ``security_details`` raises 404 inside, the aggregator
    # catches and continues. So response is 200 with empty data + warnings.
    assert r.status_code == 200
    body = r.json()
    assert body["security"]["symbol"] == "UNKNOWN"
    assert isinstance(body["warnings"], list)
