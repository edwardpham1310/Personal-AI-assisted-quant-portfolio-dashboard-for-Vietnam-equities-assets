"""Tests for GET /market/regime (VNINDEX trend heuristic)."""

from __future__ import annotations

import asyncio

from fastapi.testclient import TestClient


def test_regime_requires_auth(client: TestClient) -> None:
    assert client.get("/market/regime").status_code == 401


def test_regime_returns_labeled_score(client: TestClient, auth_headers) -> None:
    headers, _ = auth_headers()
    r = client.get("/market/regime", headers=headers)
    assert r.status_code == 200
    body = r.json()
    assert body["score"] in {30, 50, 60, 80}
    assert body["label"] in {"UPTREND", "MIXED", "DOWNTREND", "NO_DATA"}
    # The mock provider returns a full VNINDEX daily history → enough bars for a
    # real verdict (not the 50 no-data fallback).
    assert body["bars_used"] >= 60
    assert body["data_status"] == "FRESH"
    assert body["score"] != 50


def test_regime_result_is_cached(client: TestClient, auth_headers, fake_cache) -> None:
    headers, _ = auth_headers()
    client.get("/market/regime", headers=headers)
    cached = asyncio.run(fake_cache.get_json("market:regime"))
    assert cached is not None
    assert "score" in cached and "label" in cached
