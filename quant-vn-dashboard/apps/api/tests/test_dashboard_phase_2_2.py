"""Phase 2.2 dashboard APIs: PnL waterfall + portfolio equity curve.

Round-trip via TestClient (FastAPI + FakeSupabaseDB), plus a thin service-level
check for the snapshot writer. No trading paths touched.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

from fastapi.testclient import TestClient

from schemas.market import Quote
from services import market_cache


def _seed_quote(fake_cache, symbol: str, price: float) -> None:
    q = Quote(symbol=symbol, exchange="HOSE", price=price, ts=datetime.now(UTC), source="mock")
    fake_cache._data[market_cache.QUOTE_KEY.format(symbol=symbol)] = (
        json.dumps(q.model_dump(mode="json"), default=str),
        None,
    )


def _account_id(fake_db) -> str:
    return fake_db._tables["manual_portfolio_accounts"][0]["id"]


def _add_trade(fake_db, account_id: str, **fields) -> None:
    row = {"account_id": account_id, **fields}
    fake_db._tables.setdefault("trade_transactions", []).append(row)


# ── PnL waterfall ────────────────────────────────────────────────────────────


def test_waterfall_requires_auth(client: TestClient) -> None:
    assert client.get("/assets/pnl/waterfall").status_code == 401


def test_waterfall_honest_empty_no_account(client: TestClient, auth_headers) -> None:
    headers, _ = auth_headers()
    r = client.get("/assets/pnl/waterfall", headers=headers)
    assert r.status_code == 200
    body = r.json()
    assert body["buckets"] == []
    assert body["as_of"] is None
    assert "Research only" in body["disclaimer"]


def test_waterfall_seeded_returns_four_buckets_with_net_identity(
    client: TestClient, auth_headers, fake_db, fake_cache
) -> None:
    headers, _ = auth_headers()
    _seed_quote(fake_cache, "FPT", 70.0)
    # Position drives unrealized: 100 * (70 - 50) = 2000.
    client.post(
        "/portfolio/positions",
        headers=headers,
        json={"symbol": "FPT", "quantity": 100, "avg_cost": 50.0},
    )
    acct = _account_id(fake_db)
    # Trades drive realized (gross) + costs. Realized = 60 * (70 - 50) = 1200.
    _add_trade(fake_db, acct, symbol="FPT", side="BUY", quantity=100, price=50.0,
               trade_date="2026-05-01", brokerage_fee=100)
    _add_trade(fake_db, acct, symbol="FPT", side="SELL", quantity=60, price=70.0,
               trade_date="2026-05-05", brokerage_fee=50, sell_tax=30)

    r = client.get("/assets/pnl/waterfall", headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    buckets = body["buckets"]
    assert [b["bucket"] for b in buckets] == ["Realized", "Unrealized", "Costs", "Net"]
    vals = {b["bucket"]: b["value"] for b in buckets}
    assert vals["Realized"] == 1200.0  # gross, unchanged by fees
    assert vals["Unrealized"] == 2000.0
    assert vals["Costs"] == -180.0  # 100 + 50 + 30, negated
    assert vals["Net"] == 1200.0 + 2000.0 - 180.0
    # Net == arithmetic sum of the prior three buckets (no double-count).
    assert abs(vals["Net"] - (vals["Realized"] + vals["Unrealized"] + vals["Costs"])) < 1e-9
    assert body["as_of"] is not None  # quote was marked


def test_waterfall_cold_cache_stable_shape(
    client: TestClient, auth_headers, fake_db
) -> None:
    headers, _ = auth_headers()
    # Position but NO seeded quote → unrealized degrades to 0, no 500.
    client.post(
        "/portfolio/positions",
        headers=headers,
        json={"symbol": "FPT", "quantity": 100, "avg_cost": 50.0},
    )
    acct = _account_id(fake_db)
    _add_trade(fake_db, acct, symbol="FPT", side="BUY", quantity=100, price=50.0,
               trade_date="2026-05-01")
    _add_trade(fake_db, acct, symbol="FPT", side="SELL", quantity=40, price=60.0,
               trade_date="2026-05-05", brokerage_fee=20)

    r = client.get("/assets/pnl/waterfall", headers=headers)
    assert r.status_code == 200, r.text  # no 500 on cold cache
    vals = {b["bucket"]: b["value"] for b in r.json()["buckets"]}
    assert len(vals) == 4
    # Cold cache mirrors /assets/pnl exactly: unpriced position contributes
    # 0 market value but full cost basis → unrealized = -cost_basis = -5000.
    # (In production the poller is warm during market hours.)
    assert vals["Unrealized"] == -5000.0
    assert vals["Realized"] == 40 * (60.0 - 50.0)
    assert vals["Costs"] == -20.0
    # Net identity holds regardless of cache warmth.
    assert abs(vals["Net"] - (vals["Realized"] + vals["Unrealized"] + vals["Costs"])) < 1e-9


# ── Equity curve + snapshot writer ───────────────────────────────────────────


def test_equity_curve_requires_auth(client: TestClient) -> None:
    assert client.get("/portfolio/equity-curve").status_code == 401
    assert client.post("/portfolio/snapshots/run").status_code == 401


def test_equity_curve_honest_empty_no_account(client: TestClient, auth_headers) -> None:
    headers, _ = auth_headers()
    r = client.get("/portfolio/equity-curve", headers=headers)
    assert r.status_code == 200
    assert r.json() == []


def test_snapshot_run_no_account_is_not_recorded(client: TestClient, auth_headers) -> None:
    headers, _ = auth_headers()
    r = client.post("/portfolio/snapshots/run", headers=headers)
    assert r.status_code == 200
    body = r.json()
    assert body["recorded"] is False
    assert body["reason"] == "no_account"


def test_snapshot_run_then_curve_returns_marked_nav(
    client: TestClient, auth_headers, fake_cache
) -> None:
    headers, _ = auth_headers()
    _seed_quote(fake_cache, "FPT", 70.0)
    client.post(
        "/portfolio/positions",
        headers=headers,
        json={"symbol": "FPT", "quantity": 100, "avg_cost": 50.0},
    )
    run = client.post("/portfolio/snapshots/run", headers=headers)
    assert run.status_code == 200, run.text
    rb = run.json()
    assert rb["recorded"] is True
    # NAV = cash(0) + stock_value(100*70) = 7,000,000? here 7000 with test units.
    assert rb["total_equity"] == 7000.0

    curve = client.get("/portfolio/equity-curve", headers=headers)
    assert curve.status_code == 200
    points = curve.json()
    assert len(points) == 1
    assert points[0]["equity"] == 7000.0
    assert points[0]["ts"] == rb["snapshot_date"]


def test_snapshot_run_is_idempotent_per_day(
    client: TestClient, auth_headers, fake_db, fake_cache
) -> None:
    headers, _ = auth_headers()
    _seed_quote(fake_cache, "FPT", 70.0)
    client.post(
        "/portfolio/positions",
        headers=headers,
        json={"symbol": "FPT", "quantity": 100, "avg_cost": 50.0},
    )
    client.post("/portfolio/snapshots/run", headers=headers)
    client.post("/portfolio/snapshots/run", headers=headers)

    # Only one row for today — the second call updated, not appended.
    assert len(fake_db._tables["portfolio_equity_snapshots"]) == 1
    points = client.get("/portfolio/equity-curve", headers=headers).json()
    assert len(points) == 1


def _add_snapshot(fake_db, user_id: str, account_id: str, snapshot_date: str, equity: float) -> None:
    fake_db._tables.setdefault("portfolio_equity_snapshots", []).append(
        {
            "id": f"snap-{snapshot_date}",
            "user_id": user_id,
            "account_id": account_id,
            "snapshot_date": snapshot_date,
            "total_equity": equity,
        }
    )


def test_equity_curve_calendar_filter_and_ascending(
    client: TestClient, auth_headers, fake_db
) -> None:
    headers, uid = auth_headers()
    # Create the default account (no quote needed — we seed snapshots directly).
    client.post(
        "/portfolio/positions",
        headers=headers,
        json={"symbol": "FPT", "quantity": 100, "avg_cost": 50.0},
    )
    acct = _account_id(fake_db)
    # Seed three days OUT OF ORDER to prove the route sorts ascending.
    _add_snapshot(fake_db, uid, acct, "2026-06-01", 7000.0)
    _add_snapshot(fake_db, uid, acct, "2026-01-01", 5000.0)
    _add_snapshot(fake_db, uid, acct, "2026-03-15", 6000.0)

    # No params → full history, ascending.
    full = client.get("/portfolio/equity-curve", headers=headers).json()
    assert [p["ts"] for p in full] == ["2026-01-01", "2026-03-15", "2026-06-01"]

    # Calendar window keeps only the in-range days (inclusive).
    windowed = client.get(
        "/portfolio/equity-curve?start=2026-03-01&end=2026-06-30", headers=headers
    ).json()
    assert [p["ts"] for p in windowed] == ["2026-03-15", "2026-06-01"]

    # Window with no data → honest empty.
    empty = client.get(
        "/portfolio/equity-curve?start=2030-01-01&end=2030-12-31", headers=headers
    ).json()
    assert empty == []


def test_equity_curve_rejects_inverted_range(client: TestClient, auth_headers) -> None:
    headers, _ = auth_headers()
    r = client.get(
        "/portfolio/equity-curve?start=2026-06-01&end=2026-01-01", headers=headers
    )
    assert r.status_code == 400


def test_equity_curve_isolated_by_user(
    client: TestClient, auth_headers, fake_cache
) -> None:
    headers_a, _ = auth_headers()
    _seed_quote(fake_cache, "FPT", 70.0)
    client.post(
        "/portfolio/positions",
        headers=headers_a,
        json={"symbol": "FPT", "quantity": 100, "avg_cost": 50.0},
    )
    client.post("/portfolio/snapshots/run", headers=headers_a)

    headers_b, _ = auth_headers()
    r = client.get("/portfolio/equity-curve", headers=headers_b)
    assert r.status_code == 200
    assert r.json() == []


def test_snapshot_skips_when_quote_cache_cold(
    client: TestClient, auth_headers, fake_db
) -> None:
    # A held position with NO seeded quote → NAV would understate stock value.
    # The writer must refuse to persist a misleading point.
    headers, _ = auth_headers()
    client.post(
        "/portfolio/positions",
        headers=headers,
        json={"symbol": "FPT", "quantity": 100, "avg_cost": 50.0},
    )
    r = client.post("/portfolio/snapshots/run", headers=headers)
    assert r.status_code == 200
    body = r.json()
    assert body["recorded"] is False
    assert body["reason"] == "quotes_unavailable"
    assert any("quote_missing" in w for w in body["warnings"])
    # Nothing was written, and the curve stays honestly empty.
    assert fake_db._tables.get("portfolio_equity_snapshots", []) == []
    assert client.get("/portfolio/equity-curve", headers=headers).json() == []


def test_snapshot_records_cash_only_account(
    client: TestClient, auth_headers, fake_db
) -> None:
    # An account with cash but NO positions has no unpriced stock, so the NAV is
    # fully real and the snapshot records (NAV == cash).
    headers, uid = auth_headers()
    acct_id = "acc-cash-only"
    fake_db._tables["manual_portfolio_accounts"].append(
        {"id": acct_id, "user_id": uid, "name": "Default", "created_at": "2026-01-01"}
    )
    fake_db._tables.setdefault("cash_balances", []).append(
        {"id": "cb-1", "account_id": acct_id, "settled_cash": 5_000_000}
    )
    r = client.post("/portfolio/snapshots/run", headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["recorded"] is True
    assert body["reason"] is None
    assert body["total_equity"] == 5_000_000
    points = client.get("/portfolio/equity-curve", headers=headers).json()
    assert len(points) == 1
    assert points[0]["equity"] == 5_000_000
