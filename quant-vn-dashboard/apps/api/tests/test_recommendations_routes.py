"""Round-trip route tests for the recommendation engine."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


# ── Auth ────────────────────────────────────────────────────────────────────


def test_symbol_requires_auth(client: TestClient) -> None:
    assert client.get("/recommendations/symbol/FPT").status_code == 401


def test_watchlist_requires_auth(client: TestClient) -> None:
    assert (
        client.get("/recommendations/watchlist/00000000-0000-0000-0000-000000000000")
        .status_code
        == 401
    )


def test_preview_requires_auth(client: TestClient) -> None:
    assert (
        client.post(
            "/recommendations/preview",
            json={"symbol": "FPT", "profile": "short_aggressive"},
        ).status_code
        == 401
    )


# ── /symbol ────────────────────────────────────────────────────────────────


def test_symbol_returns_full_schema(client: TestClient, auth_headers) -> None:
    headers, _ = auth_headers()
    r = client.get(
        "/recommendations/symbol/FPT?profile=short_aggressive&horizon=SHORT_2W",
        headers=headers,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    for key in [
        "symbol", "profile", "horizon", "action", "status", "confidence",
        "final_score", "scores", "reasons", "warnings", "as_of", "disclaimer",
    ]:
        assert key in body, f"missing key: {key}"
    assert body["symbol"] == "FPT"
    assert body["disclaimer"].startswith("research signal")
    assert isinstance(body["reasons"], list) and len(body["reasons"]) >= 3
    assert 0.0 <= body["confidence"] <= 1.0


def test_symbol_unknown_returns_data_unavailable(
    client: TestClient, auth_headers
) -> None:
    """Phase 2 data policy: unknown symbol must surface as a recommendation
    row with ``data_status=DATA_UNAVAILABLE`` and ``action=REJECTED`` so
    the UI can render the freshness badge — never a silent 404 or a
    confident recommendation backed by nothing.
    """
    headers, _ = auth_headers()
    r = client.get("/recommendations/symbol/NOSUCH", headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["symbol"] == "NOSUCH"
    assert body["data_status"] in {"DATA_UNAVAILABLE", "PROVIDER_ERROR"}
    assert body["action"] == "REJECTED"
    assert body["status"] == "REJECTED"
    assert body["confidence"] == 0.0
    assert body["chart_url"] == "/market/NOSUCH"


def test_symbol_400_on_invalid_symbol(client: TestClient, auth_headers) -> None:
    headers, _ = auth_headers()
    r = client.get("/recommendations/symbol/!@#", headers=headers)
    assert r.status_code == 400


def test_symbol_default_horizon_resolves(client: TestClient, auth_headers) -> None:
    headers, _ = auth_headers()
    r = client.get(
        "/recommendations/symbol/FPT?profile=long_conservative", headers=headers
    )
    assert r.status_code == 200
    assert r.json()["horizon"] == "LONG_6M"


# ── /watchlist ─────────────────────────────────────────────────────────────


def test_watchlist_empty_returns_empty_list(
    client: TestClient, auth_headers, fake_db
) -> None:
    headers, uid = auth_headers()
    # Seed a watchlist with no items.
    wl = fake_db._tables["watchlists"]
    wl.append(
        {
            "id": "11111111-1111-1111-1111-111111111111",
            "user_id": uid,
            "name": "Empty",
            "description": None,
        }
    )
    r = client.get(
        "/recommendations/watchlist/11111111-1111-1111-1111-111111111111",
        headers=headers,
    )
    assert r.status_code == 200
    assert r.json() == []


def test_watchlist_returns_per_symbol_results(
    client: TestClient, auth_headers, fake_db
) -> None:
    headers, uid = auth_headers()
    wl_id = "22222222-2222-2222-2222-222222222222"
    fake_db._tables["watchlists"].append(
        {"id": wl_id, "user_id": uid, "name": "Two", "description": None}
    )
    fake_db._tables["watchlist_items"].extend(
        [
            {"id": "a", "watchlist_id": wl_id, "symbol": "FPT", "exchange": "HOSE"},
            {"id": "b", "watchlist_id": wl_id, "symbol": "MWG", "exchange": "HOSE"},
        ]
    )
    r = client.get(
        f"/recommendations/watchlist/{wl_id}?profile=short_aggressive", headers=headers
    )
    assert r.status_code == 200
    body = r.json()
    assert len(body) == 2
    syms = {row["symbol"] for row in body}
    assert syms == {"FPT", "MWG"}


def test_watchlist_404_when_not_owned(client: TestClient, auth_headers) -> None:
    headers, _ = auth_headers()
    r = client.get(
        "/recommendations/watchlist/99999999-9999-9999-9999-999999999999",
        headers=headers,
    )
    assert r.status_code == 404


# ── /preview ───────────────────────────────────────────────────────────────


def test_preview_returns_schema_without_persisting(
    client: TestClient, auth_headers, fake_db
) -> None:
    headers, _ = auth_headers()
    before = list(fake_db._tables.get("recommendation_snapshots", []))
    r = client.post(
        "/recommendations/preview",
        headers=headers,
        json={
            "symbol": "FPT",
            "profile": "short_aggressive",
            "horizon": "SHORT_2W",
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["symbol"] == "FPT"
    # No new snapshot row inserted.
    after = list(fake_db._tables.get("recommendation_snapshots", []))
    assert len(after) == len(before)


def test_preview_400_on_invalid_symbol(client: TestClient, auth_headers) -> None:
    headers, _ = auth_headers()
    r = client.post(
        "/recommendations/preview",
        headers=headers,
        json={"symbol": "!@#", "profile": "short_aggressive"},
    )
    assert r.status_code == 400


# ── disclaimers ────────────────────────────────────────────────────────────


def test_response_contains_research_disclaimer(
    client: TestClient, auth_headers
) -> None:
    headers, _ = auth_headers()
    r = client.get(
        "/recommendations/symbol/FPT?profile=short_aggressive", headers=headers
    )
    assert r.status_code == 200
    assert "research signal" in r.json()["disclaimer"]


# ── Phase 2 chart context + data_status ────────────────────────────────────


def test_symbol_response_includes_phase2_chart_fields(
    client: TestClient, auth_headers
) -> None:
    """Every recommendation must carry the Phase 2 chart fields so the UI
    can render the freshness badge + view-chart deep link inline.
    """
    headers, _ = auth_headers()
    r = client.get(
        "/recommendations/symbol/FPT?profile=short_aggressive&horizon=SHORT_2W",
        headers=headers,
    )
    assert r.status_code == 200, r.text
    body = r.json()

    # data_status must be one of the closed set.
    assert body["data_status"] in {
        "FRESH", "STALE", "DATA_UNAVAILABLE", "PROVIDER_ERROR",
    }

    # chart_url must deep-link to /market/{symbol}.
    assert body["chart_url"] == "/market/FPT"

    # chart_context populated (engine builds it from indicators it
    # already computed).
    ctx = body.get("chart_context")
    assert ctx is not None, "chart_context missing"
    for key in (
        "timeframe",
        "last_candle_time",
        "trend",
        "ma20",
        "ma50",
        "rsi",
        "volume_ratio_20d",
        "atr14",
    ):
        assert key in ctx, f"chart_context missing key: {key}"
    assert ctx["timeframe"] == "1d"

    # latest_quote present when a quote was fetched (mock provider
    # always returns one for known symbols).
    lq = body.get("latest_quote")
    if lq is not None:
        # Carries the enriched fields the Phase 2 schema added.
        for key in ("symbol", "price", "source", "ts"):
            assert key in lq, f"latest_quote missing key: {key}"


def test_fresh_quote_yields_fresh_data_status(
    client: TestClient, auth_headers
) -> None:
    """When bars + non-stale quote are present, data_status must be FRESH."""
    headers, _ = auth_headers()
    r = client.get(
        "/recommendations/symbol/FPT?profile=short_aggressive&horizon=SHORT_2W",
        headers=headers,
    )
    body = r.json()
    # Mock provider returns non-stale quotes synchronously, so a happy
    # path call must report FRESH.
    assert body["data_status"] == "FRESH"


def test_data_unavailable_response_is_research_only(
    client: TestClient, auth_headers
) -> None:
    """A DATA_UNAVAILABLE recommendation must NOT carry a confident action.

    Phase 2 rule: never silently generate from fake data; instead surface
    REJECTED + 0 confidence + clear warning so the operator can act.
    """
    headers, _ = auth_headers()
    r = client.get("/recommendations/symbol/UNKNOWN_SYM", headers=headers)
    body = r.json()
    assert body["action"] == "REJECTED"
    assert body["confidence"] == 0.0
    assert body["final_score"] == 0
    # Disclaimer still present — research-only stance is unchanged.
    assert body["disclaimer"].startswith("research signal")
