"""Feature 5 — /recommendations/history + /performance."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from schemas.market import Quote
from services import market_cache


def _iso(days_ago: float) -> str:
    return (datetime.now(UTC) - timedelta(days=days_ago)).isoformat()


def _snap(uid: str, **over) -> dict:
    base = {
        "user_id": uid,
        "symbol": "FPT",
        "horizon": "SHORT_2W",
        "action": "BUY_CANDIDATE",
        "profile": "short_aggressive",
        "confidence": 0.7,
        "status": "OPEN",
        "reasons": ["Uptrend with volume confirmation"],
        "warnings": [],
        "scores": {
            "trend": 80, "momentum": 75, "volume": 70, "liquidity": 60,
            "risk": 30, "risk_inverse": 70, "market_regime": 60,
            "portfolio_fit": 100, "ml_probability": None,
        },
        "reference_price": 100.0,
        "created_at": _iso(1),
        "as_of": _iso(1),
    }
    base.update(over)
    return base


def _seed_quote(cache, symbol: str, price: float, *, stale: bool = False) -> None:
    q = Quote(
        symbol=symbol, exchange="HOSE", price=price, reference_price=price,
        change=0, change_pct=0, volume=1000, value=price * 1000,
        ts=datetime.now(UTC), stale=stale, source="test",
    )
    asyncio.run(market_cache.set_quote(cache, q, ttl_seconds=300))


# ── history ───────────────────────────────────────────────────────────────────


def test_history_requires_auth(client: TestClient) -> None:
    assert client.get("/recommendations/history").status_code == 401
    assert client.get("/recommendations/performance").status_code == 401


def test_history_empty_is_honest(client: TestClient, auth_headers) -> None:
    headers, _ = auth_headers()
    r = client.get("/recommendations/history", headers=headers)
    assert r.status_code == 200
    body = r.json()
    assert body["items"] == []
    assert body["count"] == 0
    assert body["disclaimer"].startswith("research signal")


def test_history_returns_items_sorted_ascending(client: TestClient, auth_headers, fake_db) -> None:
    headers, uid = auth_headers()
    fake_db._tables["recommendation_snapshots"].extend(
        [
            _snap(uid, id="b", created_at=_iso(1), as_of=_iso(1)),
            _snap(uid, id="a", created_at=_iso(5), as_of=_iso(5)),
        ]
    )
    r = client.get("/recommendations/history", headers=headers)
    assert r.status_code == 200, r.text
    items = r.json()["items"]
    assert [it["id"] for it in items] == ["a", "b"]  # oldest → newest
    # display vocabulary present + recomputed score
    assert items[0]["strength"] in {"Weak", "Neutral", "Strong"}
    assert items[0]["signal"] in {
        "Watch", "Actionable", "Accumulate", "Wait", "Avoid", "Risky", "Take Profit"
    }
    assert items[0]["final_score"] > 0


def test_history_range_filters_old_rows(client: TestClient, auth_headers, fake_db) -> None:
    headers, uid = auth_headers()
    fake_db._tables["recommendation_snapshots"].extend(
        [
            _snap(uid, id="recent", created_at=_iso(2), as_of=_iso(2)),
            _snap(uid, id="old", created_at=_iso(400), as_of=_iso(400)),
        ]
    )
    r = client.get("/recommendations/history?range=1M", headers=headers)
    ids = [it["id"] for it in r.json()["items"]]
    assert ids == ["recent"]


def test_history_symbol_filter(client: TestClient, auth_headers, fake_db) -> None:
    headers, uid = auth_headers()
    fake_db._tables["recommendation_snapshots"].extend(
        [_snap(uid, id="f", symbol="FPT"), _snap(uid, id="m", symbol="MWG")]
    )
    r = client.get("/recommendations/history?symbol=mwg", headers=headers)
    items = r.json()["items"]
    assert [it["symbol"] for it in items] == ["MWG"]


def test_history_is_user_scoped(client: TestClient, auth_headers, fake_db) -> None:
    headers_a, uid_a = auth_headers()
    fake_db._tables["recommendation_snapshots"].append(_snap(uid_a, id="mine"))
    headers_b, _ = auth_headers()
    assert client.get("/recommendations/history", headers=headers_b).json()["items"] == []


# ── performance ───────────────────────────────────────────────────────────────


def test_performance_empty_is_honest(client: TestClient, auth_headers) -> None:
    headers, _ = auth_headers()
    r = client.get("/recommendations/performance", headers=headers)
    assert r.status_code == 200
    body = r.json()
    assert body["evaluated"] == 0
    assert body["win_rate"] is None
    assert body["avg_return_pct"] is None
    assert "hypothetical" in body["disclaimer"].lower()
    assert "not an executed trade" in body["disclaimer"].lower()


def test_performance_computes_hypothetical_return(
    client: TestClient, auth_headers, fake_db, fake_cache
) -> None:
    headers, uid = auth_headers()
    fake_db._tables["recommendation_snapshots"].append(
        _snap(uid, id="x", symbol="FPT", reference_price=100.0)
    )
    _seed_quote(fake_cache, "FPT", 110.0)
    r = client.get("/recommendations/performance", headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["evaluated"] == 1
    assert body["total"] == 1
    item = body["items"][0]
    assert item["reference_price"] == 100.0
    assert item["current_price"] == 110.0
    assert abs(item["return_pct"] - 0.10) < 1e-9
    assert body["win_rate"] == 1.0
    assert abs(body["avg_return_pct"] - 0.10) < 1e-9
    assert body["best"]["symbol"] == "FPT"


def test_performance_skips_rows_without_reference_or_quote(
    client: TestClient, auth_headers, fake_db, fake_cache
) -> None:
    headers, uid = auth_headers()
    fake_db._tables["recommendation_snapshots"].extend(
        [
            _snap(uid, id="noref", symbol="FPT", reference_price=None),
            _snap(uid, id="noquote", symbol="VCB", reference_price=50.0),
        ]
    )
    # No quote seeded for VCB → that row is skipped for lack of a current price.
    r = client.get("/recommendations/performance", headers=headers)
    body = r.json()
    assert body["evaluated"] == 0
    assert body["skipped_no_reference"] == 1
    assert body["skipped_no_quote"] == 1
    assert body["total"] == 2
