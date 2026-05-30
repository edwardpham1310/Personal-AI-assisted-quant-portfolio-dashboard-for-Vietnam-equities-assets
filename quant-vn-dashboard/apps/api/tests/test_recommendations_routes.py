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


def test_symbol_404_on_unknown(client: TestClient, auth_headers) -> None:
    headers, _ = auth_headers()
    r = client.get("/recommendations/symbol/NOSUCH", headers=headers)
    assert r.status_code == 404


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
