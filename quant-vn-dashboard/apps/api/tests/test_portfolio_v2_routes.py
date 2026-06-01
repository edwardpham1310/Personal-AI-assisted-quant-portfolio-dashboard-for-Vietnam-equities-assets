"""Phase 1 portfolio + assets endpoints (round-trip via TestClient)."""

from __future__ import annotations

import json
from datetime import UTC, datetime

from fastapi.testclient import TestClient

from schemas.market import Quote
from services import market_cache


def _seed_quote(fake_cache, symbol: str, price: float) -> None:
    """Drop a pre-cooked Quote into the in-memory cache via market_cache keys."""
    q = Quote(
        symbol=symbol,
        exchange="HOSE",
        price=price,
        ts=datetime.now(UTC),
        source="mock",
    )
    # Synchronous shim — InMemoryCache stores str values.
    fake_cache._data[market_cache.QUOTE_KEY.format(symbol=symbol)] = (
        json.dumps(q.model_dump(mode="json"), default=str),
        None,
    )


# ── Summary + positions ──────────────────────────────────────────────────────


def test_summary_requires_auth(client: TestClient) -> None:
    assert client.get("/portfolio/summary").status_code == 401
    assert client.get("/portfolio/positions").status_code == 401


def test_summary_new_user_returns_zeros(client: TestClient, auth_headers) -> None:
    headers, _ = auth_headers()
    r = client.get("/portfolio/summary", headers=headers)
    assert r.status_code == 200
    body = r.json()
    assert body["total_market_value"] == 0.0
    assert body["total_cost_basis"] == 0.0
    assert body["position_count"] == 0
    assert body["by_strategy_tag"] == {}


def test_positions_new_user_returns_empty(client: TestClient, auth_headers) -> None:
    headers, _ = auth_headers()
    r = client.get("/portfolio/positions", headers=headers)
    assert r.status_code == 200
    assert r.json() == []


def test_post_position_autocreates_default_account(
    client: TestClient, auth_headers, fake_db
) -> None:
    headers, uid = auth_headers()
    # No account yet.
    assert fake_db._tables["manual_portfolio_accounts"] == []

    r = client.post(
        "/portfolio/positions",
        headers=headers,
        json={
            "symbol": "fpt",
            "quantity": 100,
            "avg_cost": 50.0,
            "strategy_tag": "tech",
        },
    )
    assert r.status_code == 201, r.text
    pos = r.json()
    assert pos["symbol"] == "FPT"
    assert pos["quantity"] == 100

    # Default account materialized.
    accounts = fake_db._tables["manual_portfolio_accounts"]
    assert len(accounts) == 1
    assert accounts[0]["user_id"] == uid
    assert accounts[0]["name"] == "Default"


def test_get_positions_returns_enriched_rows(
    client: TestClient, auth_headers, fake_cache
) -> None:
    headers, _ = auth_headers()
    _seed_quote(fake_cache, "FPT", 70.0)

    client.post(
        "/portfolio/positions",
        headers=headers,
        json={"symbol": "FPT", "quantity": 100, "avg_cost": 50.0},
    )

    r = client.get("/portfolio/positions", headers=headers)
    assert r.status_code == 200
    rows = r.json()
    assert len(rows) == 1
    row = rows[0]
    assert row["symbol"] == "FPT"
    assert row["market_price"] == 70.0
    assert row["market_value"] == 7000.0
    assert row["unrealized_pnl"] == 2000.0


def test_get_summary_aggregates_priced_positions(
    client: TestClient, auth_headers, fake_cache
) -> None:
    headers, _ = auth_headers()
    _seed_quote(fake_cache, "FPT", 70.0)
    # MWG intentionally has no seeded quote.

    client.post(
        "/portfolio/positions",
        headers=headers,
        json={"symbol": "FPT", "quantity": 100, "avg_cost": 50.0, "strategy_tag": "tech"},
    )
    client.post(
        "/portfolio/positions",
        headers=headers,
        json={"symbol": "MWG", "quantity": 50, "avg_cost": 40.0, "strategy_tag": "retail"},
    )

    r = client.get("/portfolio/summary", headers=headers)
    assert r.status_code == 200
    body = r.json()
    assert body["position_count"] == 2
    assert body["total_market_value"] == 7000.0
    # Cost basis includes both even when one quote is missing.
    assert body["total_cost_basis"] == 100 * 50.0 + 50 * 40.0
    assert any("MWG" in w for w in body["warnings"])


def test_put_and_delete_position(
    client: TestClient, auth_headers
) -> None:
    headers, _ = auth_headers()
    created = client.post(
        "/portfolio/positions",
        headers=headers,
        json={"symbol": "HPG", "quantity": 100, "avg_cost": 25000.0},
    ).json()

    put = client.put(
        f"/portfolio/positions/{created['id']}",
        headers=headers,
        json={"quantity": 200, "avg_cost": 26000.0},
    )
    assert put.status_code == 200
    assert put.json()["quantity"] == 200

    delete = client.delete(
        f"/portfolio/positions/{created['id']}", headers=headers
    )
    assert delete.status_code == 204


def test_put_unknown_position_404(client: TestClient, auth_headers) -> None:
    headers, _ = auth_headers()
    r = client.put(
        "/portfolio/positions/00000000-0000-0000-0000-000000000000",
        headers=headers,
        json={"quantity": 50},
    )
    assert r.status_code == 404


def test_put_empty_payload_400(client: TestClient, auth_headers) -> None:
    headers, _ = auth_headers()
    created = client.post(
        "/portfolio/positions",
        headers=headers,
        json={"symbol": "HPG", "quantity": 100, "avg_cost": 25000.0},
    ).json()
    r = client.put(
        f"/portfolio/positions/{created['id']}", headers=headers, json={}
    )
    assert r.status_code == 400


# ── Assets ───────────────────────────────────────────────────────────────────


def test_assets_summary_requires_auth(client: TestClient) -> None:
    assert client.get("/assets/summary").status_code == 401


def test_assets_summary_new_user_returns_zero_equity(
    client: TestClient, auth_headers
) -> None:
    headers, _ = auth_headers()
    r = client.get("/assets/summary", headers=headers)
    assert r.status_code == 200
    body = r.json()
    assert body["stock_market_value"] == 0.0
    assert body["total_equity"] == 0.0
    assert body["available_buying_power"] == 0.0
    assert body["cash"]["settled_cash"] == 0.0


def test_assets_pnl_with_no_trades_returns_zero(
    client: TestClient, auth_headers
) -> None:
    headers, _ = auth_headers()
    r = client.get("/assets/pnl", headers=headers)
    assert r.status_code == 200
    body = r.json()
    assert body["realized"]["amount"] == 0.0
    assert body["unrealized"]["amount"] == 0.0
    assert body["by_symbol"] == []


def test_assets_costs_all_period_empty(
    client: TestClient, auth_headers
) -> None:
    headers, _ = auth_headers()
    r = client.get("/assets/costs?period=ALL", headers=headers)
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 0.0
    assert body["trade_count"] == 0
    assert body["period"] == "ALL"


# ── SSI sync placeholder ─────────────────────────────────────────────────────


def test_sync_ssi_returns_501_placeholder(
    client: TestClient, auth_headers
) -> None:
    headers, _ = auth_headers()
    r = client.post("/portfolio/sync/ssi", headers=headers)
    assert r.status_code == 501
    body = r.json()
    assert body["status"] == "placeholder"
    assert "Phase 2" in body["detail"]


def test_pending_cash_is_NOT_counted_as_available_buying_power(
    client: TestClient, auth_headers, fake_db
) -> None:
    """Phase 1 safety rule: pending_cash sitting unsettled must NOT inflate
    the buying-power figure shown to the user. Only settled_cash counts.
    """
    headers, uid = auth_headers()

    # Trigger account creation via the default-account POST path.
    r = client.post(
        "/portfolio/positions",
        headers=headers,
        json={"symbol": "FPT", "quantity": 100, "avg_cost": 70.0},
    )
    assert r.status_code == 201, r.text
    account_id = fake_db._tables["manual_portfolio_accounts"][0]["id"]

    # Seed a cash row with substantial pending_cash but only modest settled.
    fake_db._tables.setdefault("cash_balances", []).append(
        {
            "id": "cb-1",
            "account_id": account_id,
            "settled_cash": 1_000_000,
            "pending_cash": 50_000_000,  # T+2 unsettled — must NOT inflate BP
            "advanced_cash": 0,
            "cash_advance_liability": 0,
            "withdrawable_cash": 0,
            "currency": "VND",
        }
    )

    r = client.get("/assets/summary", headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    # Buying power should reflect ONLY settled_cash, not pending.
    assert body["available_buying_power"] == 1_000_000
    # But total_equity DOES include pending (it counts toward net worth).
    assert body["total_equity"] >= 1_000_000 + 50_000_000
    # And pending_cash is surfaced separately in the cash bucket.
    assert body["cash"]["pending_cash"] == 50_000_000
    assert body["cash"]["settled_cash"] == 1_000_000


def test_user_b_cannot_read_user_a_default_account_endpoints(
    client: TestClient, auth_headers, fake_db
) -> None:
    """Default-account v2 surfaces (`/portfolio/summary`, `/portfolio/positions`,
    `/assets/summary`) must isolate by user_id from the JWT — never accept
    a user-id from the request body and never resolve another user's account.
    """
    headers_a, uid_a = auth_headers()
    headers_b, uid_b = auth_headers()
    assert uid_a != uid_b

    # User A: create a position under their default account.
    r = client.post(
        "/portfolio/positions",
        headers=headers_a,
        json={"symbol": "FPT", "quantity": 100, "avg_cost": 70.0},
    )
    assert r.status_code == 201

    # User B: every default-account endpoint must see an empty portfolio.
    r = client.get("/portfolio/summary", headers=headers_b)
    assert r.status_code == 200
    assert r.json()["position_count"] == 0
    assert r.json()["total_market_value"] == 0.0

    r = client.get("/portfolio/positions", headers=headers_b)
    assert r.status_code == 200
    assert r.json() == []

    r = client.get("/assets/summary", headers=headers_b)
    assert r.status_code == 200
    body = r.json()
    assert body["stock_market_value"] == 0.0
    assert body["available_buying_power"] == 0.0
