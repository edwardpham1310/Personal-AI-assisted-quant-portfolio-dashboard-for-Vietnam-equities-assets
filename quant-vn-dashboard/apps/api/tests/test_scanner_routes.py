"""Scanner endpoint tests — uses the deterministic MockProvider via conftest."""

from __future__ import annotations

from fastapi.testclient import TestClient

REQUIRED_KEYS = {
    "symbol",
    "last_price",
    "trend",
    "signals",
    "scores",
    "status",
    "warnings",
    "as_of",
    "indicators",
}
REQUIRED_SCORE_KEYS = {"trend", "momentum", "volume", "liquidity", "risk"}
REQUIRED_INDICATOR_KEYS = {
    "ma20",
    "ma50",
    "rsi14",
    "atr14",
    "volume_ratio_20d",
    "high_20d",
    "high_55d",
    "avg_value_20d",
}


def test_scanner_requires_auth(client: TestClient) -> None:
    assert client.get("/scanner/symbol/FPT").status_code == 401
    assert client.get("/scanner/watchlist/abc").status_code == 401
    assert client.get("/scanner/universe?vn30=true").status_code == 401


def test_scanner_symbol_returns_required_shape(client: TestClient, auth_headers) -> None:
    headers, _ = auth_headers()
    r = client.get("/scanner/symbol/FPT", headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()

    assert REQUIRED_KEYS.issubset(body.keys())
    assert body["symbol"] == "FPT"
    assert body["trend"] in {"UPTREND", "DOWNTREND", "SIDEWAYS", "UNKNOWN"}
    assert body["status"] in {"BUY_CANDIDATE", "WATCH", "HOLD", "AVOID"}
    assert REQUIRED_SCORE_KEYS.issubset(body["scores"].keys())
    assert REQUIRED_INDICATOR_KEYS.issubset(body["indicators"].keys())
    # All five score buckets are bounded.
    for key in REQUIRED_SCORE_KEYS:
        val = body["scores"][key]
        assert isinstance(val, int)
        assert 0 <= val <= 100


def test_scanner_symbol_invalid_symbol_400(client: TestClient, auth_headers) -> None:
    headers, _ = auth_headers()
    r = client.get("/scanner/symbol/b@d!sym", headers=headers)
    assert r.status_code == 400
    assert "Invalid symbol" in r.json()["detail"]


def test_scanner_symbol_unknown_symbol_404(client: TestClient, auth_headers) -> None:
    headers, _ = auth_headers()
    # Mock provider rejects unknown tickers; the route surfaces a 404.
    r = client.get("/scanner/symbol/ZZZZ", headers=headers)
    assert r.status_code == 404


def test_scanner_watchlist_empty_returns_empty_list(
    client: TestClient, auth_headers
) -> None:
    headers, _ = auth_headers()
    wl = client.post("/watchlists", headers=headers, json={"name": "Empty"}).json()
    r = client.get(f"/scanner/watchlist/{wl['id']}", headers=headers)
    assert r.status_code == 200
    assert r.json() == []


def test_scanner_watchlist_with_items_returns_results(
    client: TestClient, auth_headers
) -> None:
    headers, _ = auth_headers()
    wl = client.post("/watchlists", headers=headers, json={"name": "Tech"}).json()
    add = client.post(
        f"/watchlists/{wl['id']}/items",
        headers=headers,
        json={"symbol": "FPT", "exchange": "HOSE"},
    )
    assert add.status_code == 201
    add = client.post(
        f"/watchlists/{wl['id']}/items",
        headers=headers,
        json={"symbol": "MWG", "exchange": "HOSE"},
    )
    assert add.status_code == 201

    r = client.get(f"/scanner/watchlist/{wl['id']}", headers=headers)
    assert r.status_code == 200
    rows = r.json()
    symbols = {row["symbol"] for row in rows}
    assert symbols == {"FPT", "MWG"}
    for row in rows:
        assert REQUIRED_KEYS.issubset(row.keys())


def test_scanner_watchlist_unknown_404(client: TestClient, auth_headers) -> None:
    headers, _ = auth_headers()
    r = client.get(
        "/scanner/watchlist/00000000-0000-0000-0000-000000000000", headers=headers
    )
    assert r.status_code == 404


def test_scanner_universe_vn30_returns_results(
    client: TestClient, auth_headers
) -> None:
    headers, _ = auth_headers()
    r = client.get("/scanner/universe?vn30=true", headers=headers)
    assert r.status_code == 200
    rows = r.json()
    assert isinstance(rows, list)
    assert len(rows) > 0
    syms = {row["symbol"] for row in rows}
    # MockProvider's VN30 components are {FPT, MWG, HPG, VNM}.
    assert syms == {"FPT", "MWG", "HPG", "VNM"}


def test_scanner_universe_requires_vn30_flag(client: TestClient, auth_headers) -> None:
    headers, _ = auth_headers()
    r = client.get("/scanner/universe", headers=headers)
    assert r.status_code == 400
    assert "vn30" in r.json()["detail"].lower()
