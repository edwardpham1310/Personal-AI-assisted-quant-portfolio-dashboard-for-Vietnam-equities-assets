"""Top Quant Picks — GET /recommendations/top (Feature 2).

Reuses the engine scoring (same as watchlist) over the tracked universe and
maps to safer strength/signal labels. Research signals only; no order path.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from services.recommendation_scoring import signal_from, strength_from_score

_SAFE_SIGNALS = {"Watch", "Actionable", "Accumulate", "Wait", "Avoid", "Risky", "Take Profit"}
_FORBIDDEN = ("buy", "guaranteed", "sure profit", "must")


# ── Pure label helpers ──────────────────────────────────────────────────────


def test_strength_boundaries() -> None:
    assert strength_from_score(80) == "Strong"
    assert strength_from_score(79) == "Neutral"
    assert strength_from_score(60) == "Neutral"
    assert strength_from_score(59) == "Weak"
    assert strength_from_score(0) == "Weak"


def test_signal_mapping_is_safe_vocabulary() -> None:
    assert signal_from("BUY_CANDIDATE", 80) == "Actionable"
    assert signal_from("BUY_CANDIDATE", 65) == "Accumulate"
    assert signal_from("BUY_CANDIDATE", 50) == "Watch"
    assert signal_from("WATCH", 70) == "Watch"
    assert signal_from("HOLD", 70) == "Wait"
    assert signal_from("REDUCE", 70) == "Take Profit"
    assert signal_from("SELL_CANDIDATE", 70) == "Avoid"
    assert signal_from("AVOID", 40) == "Avoid"
    assert signal_from("REJECTED", 20) == "Risky"
    # No advice wording leaks through the vocabulary.
    for action in ("BUY_CANDIDATE", "WATCH", "HOLD", "REDUCE", "SELL_CANDIDATE", "AVOID", "REJECTED"):
        label = signal_from(action, 70)
        assert label in _SAFE_SIGNALS
        assert label.lower() not in _FORBIDDEN


# ── Route ───────────────────────────────────────────────────────────────────


def test_top_requires_auth(client: TestClient) -> None:
    assert client.get("/recommendations/top").status_code == 401


def test_top_returns_ranked_picks_over_tracked_universe(client: TestClient, auth_headers) -> None:
    headers, _ = auth_headers()
    r = client.get("/recommendations/top?limit=5", headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["coverage"] == "tracked_universe"
    assert body["universe_size"] >= 1
    assert "not financial advice" in body["disclaimer"].lower()
    picks = body["picks"]
    assert len(picks) <= 5
    # Descending by quant_score; valid strength/signal vocab; no advice wording.
    scores = [p["quant_score"] for p in picks]
    assert scores == sorted(scores, reverse=True)
    for p in picks:
        assert p["strength"] in {"Weak", "Neutral", "Strong"}
        assert p["signal"] in _SAFE_SIGNALS
        assert 0 <= p["quant_score"] <= 100
        blob = (" ".join(p["reasons"]) + " " + " ".join(p["risks"]) + " " + p["signal"]).lower()
        for word in _FORBIDDEN:
            assert word not in blob


def test_top_exchange_filter_excludes_other_exchanges(client: TestClient, auth_headers) -> None:
    headers, _ = auth_headers()
    # Mock universe is HOSE; filtering to a different exchange yields no picks.
    r = client.get("/recommendations/top?exchange=HNX", headers=headers)
    assert r.status_code == 200
    assert r.json()["picks"] == []


def test_top_limit_is_respected(client: TestClient, auth_headers) -> None:
    headers, _ = auth_headers()
    r = client.get("/recommendations/top?limit=2", headers=headers)
    assert r.status_code == 200
    assert len(r.json()["picks"]) <= 2
