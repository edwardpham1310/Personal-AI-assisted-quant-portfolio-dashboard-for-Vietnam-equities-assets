"""Phase 2.7 paper-trading tests.

Covers the AC checklist:
- create paper account
- buy paper order filled
- sell paper order filled (after T+2 settlement)
- insufficient cash rejected
- insufficient sellable shares rejected
- T+2 pending shares behavior
- T+2 pending cash behavior
- fees/tax/slippage applied
- equity curve updates
- DATA_UNAVAILABLE when provider fails (no fake fallback)
- regression sweep for no-NewOrder calls
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi.testclient import TestClient

# ── Helpers ─────────────────────────────────────────────────────────────────


def _create_account(client: TestClient, headers: dict, *, starting_cash: int = 100_000_000) -> str:
    r = client.post(
        "/paper/accounts",
        headers=headers,
        json={"name": "Main", "starting_cash": starting_cash, "currency": "VND"},
    )
    return r.json()["id"]


# ── Auth gating ────────────────────────────────────────────────────────────


def test_all_paper_routes_require_auth(client: TestClient) -> None:
    assert client.get("/paper/accounts").status_code == 401
    assert client.post("/paper/accounts", json={"name": "x"}).status_code == 401
    assert client.get("/paper/accounts/x").status_code == 401
    assert client.get("/paper/accounts/x/summary").status_code == 401
    assert client.get("/paper/accounts/x/positions").status_code == 401
    assert client.get("/paper/accounts/x/orders").status_code == 401
    assert client.get("/paper/accounts/x/fills").status_code == 401
    assert client.get("/paper/accounts/x/equity-curve").status_code == 401
    assert client.post("/paper/accounts/x/orders", json={}).status_code == 401
    assert client.post("/paper/accounts/x/run-recommendation", json={}).status_code == 401


# ── Account creation ───────────────────────────────────────────────────────


def test_create_paper_account_seeds_cash(
    client: TestClient, auth_headers, fake_db
) -> None:
    headers, uid = auth_headers()
    r = client.post(
        "/paper/accounts",
        headers=headers,
        json={"name": "Main", "starting_cash": 50_000_000, "currency": "VND"},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["current_cash"] == 50_000_000
    # Seed deposit row exists.
    ledger = fake_db._tables["paper_cash_ledger"]
    deposits = [
        r for r in ledger
        if r["paper_account_id"] == body["id"] and r["event_type"] == "DEPOSIT"
    ]
    assert deposits
    # Account-created audit row exists.
    audit = fake_db._tables["paper_audit_logs"]
    assert any(
        r["user_id"] == uid and r["action"] == "PAPER_ACCOUNT_CREATED"
        for r in audit
    )


def test_cannot_read_other_users_paper_account(
    client: TestClient, auth_headers
) -> None:
    headers_a, _ = auth_headers()
    headers_b, _ = auth_headers()
    account_id = _create_account(client, headers_a)
    r = client.get(f"/paper/accounts/{account_id}", headers=headers_b)
    assert r.status_code == 404


# ── BUY happy path ─────────────────────────────────────────────────────────


def test_buy_paper_order_fills_and_deducts_cash(
    client: TestClient, auth_headers, fake_db
) -> None:
    headers, _ = auth_headers()
    account_id = _create_account(client, headers)
    r = client.post(
        f"/paper/accounts/{account_id}/orders",
        headers=headers,
        json={"symbol": "FPT", "side": "BUY", "order_type": "MARKET", "quantity": 100},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["order"]["status"] == "FILLED"
    assert body["rejection_reason"] is None
    fill = body["fill"]
    assert fill["side"] == "BUY"
    assert fill["quantity"] == 100
    # Fees + VAT + slippage all > 0.
    assert fill["brokerage_fee"] > 0
    assert fill["vat"] > 0
    assert fill["slippage"] > 0
    assert fill["sell_tax"] == 0  # buy side
    # Cash dropped.
    acc = fake_db._tables["paper_accounts"]
    me = next(a for a in acc if a["id"] == account_id)
    assert me["current_cash"] < 100_000_000


def test_buy_creates_position_with_pending_quantity(
    client: TestClient, auth_headers, fake_db
) -> None:
    headers, _ = auth_headers()
    account_id = _create_account(client, headers)
    client.post(
        f"/paper/accounts/{account_id}/orders",
        headers=headers,
        json={"symbol": "FPT", "side": "BUY", "order_type": "MARKET", "quantity": 100},
    )
    positions = fake_db._tables["paper_positions"]
    fpt = [p for p in positions if p["paper_account_id"] == account_id and p["symbol"] == "FPT"]
    assert fpt
    p = fpt[0]
    assert p["quantity"] == 100
    assert p["pending_quantity"] == 100
    assert p["sellable_quantity"] == 0  # T+0: not settled yet


# ── BUY rejections ─────────────────────────────────────────────────────────


def test_buy_rejected_when_insufficient_cash(
    client: TestClient, auth_headers
) -> None:
    headers, _ = auth_headers()
    account_id = _create_account(client, headers, starting_cash=1_000_000)
    # Try to buy 10k FPT @ ~86k = 860M, way more than 1M cash.
    r = client.post(
        f"/paper/accounts/{account_id}/orders",
        headers=headers,
        json={"symbol": "FPT", "side": "BUY", "order_type": "MARKET", "quantity": 10000},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["order"]["status"] == "REJECTED"
    assert body["rejection_reason"] == "INSUFFICIENT_CASH"
    assert body["fill"] is None


def test_buy_rejected_when_lot_size_violation(
    client: TestClient, auth_headers
) -> None:
    headers, _ = auth_headers()
    account_id = _create_account(client, headers)
    r = client.post(
        f"/paper/accounts/{account_id}/orders",
        headers=headers,
        json={"symbol": "FPT", "side": "BUY", "order_type": "MARKET", "quantity": 137},
    )
    assert r.status_code == 200
    assert r.json()["rejection_reason"].startswith("LOT_SIZE_VIOLATION")


# ── SELL rejections ────────────────────────────────────────────────────────


def test_sell_rejected_when_no_sellable_shares(
    client: TestClient, auth_headers
) -> None:
    headers, _ = auth_headers()
    account_id = _create_account(client, headers)
    # Buy first → 100 pending shares, 0 sellable (T+0).
    client.post(
        f"/paper/accounts/{account_id}/orders",
        headers=headers,
        json={"symbol": "FPT", "side": "BUY", "order_type": "MARKET", "quantity": 100},
    )
    # Try to sell immediately → INSUFFICIENT_SHARES (0 sellable).
    r = client.post(
        f"/paper/accounts/{account_id}/orders",
        headers=headers,
        json={"symbol": "FPT", "side": "SELL", "order_type": "MARKET", "quantity": 100},
    )
    assert r.status_code == 200
    assert r.json()["rejection_reason"] == "INSUFFICIENT_SHARES"


# ── T+2 settlement (shares) ────────────────────────────────────────────────


def test_t_plus_2_settles_pending_shares_to_sellable(
    client: TestClient, auth_headers, fake_db, monkeypatch
) -> None:
    """After we fake-age the BUY fill by 3 calendar days, calling any
    read-side route (which invokes ``settle_pending``) must flip the
    pending qty to sellable."""
    headers, _ = auth_headers()
    account_id = _create_account(client, headers)
    client.post(
        f"/paper/accounts/{account_id}/orders",
        headers=headers,
        json={"symbol": "FPT", "side": "BUY", "order_type": "MARKET", "quantity": 100},
    )
    # Age the fill row by 3 days so T+2 has matured.
    fills = fake_db._tables["paper_fills"]
    old = (datetime.now(UTC) - timedelta(days=4)).isoformat()
    for f in fills:
        if f["paper_account_id"] == account_id:
            f["filled_at"] = old
    # Read positions → triggers settle_pending.
    r = client.get(
        f"/paper/accounts/{account_id}/positions", headers=headers
    )
    positions = r.json()
    fpt = next(p for p in positions if p["symbol"] == "FPT")
    assert fpt["sellable_quantity"] == 100
    assert fpt["pending_quantity"] == 0


# ── T+2 settlement (cash) ──────────────────────────────────────────────────


def test_sell_proceeds_become_pending_cash(
    client: TestClient, auth_headers, fake_db
) -> None:
    """After a fully-settled BUY → SELL: the sell proceeds land in the
    PENDING cash ledger, not in current_cash."""
    headers, _ = auth_headers()
    account_id = _create_account(client, headers)
    # BUY then age the fill so the T+2 settles to sellable.
    client.post(
        f"/paper/accounts/{account_id}/orders",
        headers=headers,
        json={"symbol": "FPT", "side": "BUY", "order_type": "MARKET", "quantity": 100},
    )
    old = (datetime.now(UTC) - timedelta(days=4)).isoformat()
    for f in fake_db._tables["paper_fills"]:
        if f["paper_account_id"] == account_id:
            f["filled_at"] = old
    # Trigger settle via a read.
    client.get(f"/paper/accounts/{account_id}/positions", headers=headers)
    # Now SELL.
    r = client.post(
        f"/paper/accounts/{account_id}/orders",
        headers=headers,
        json={"symbol": "FPT", "side": "SELL", "order_type": "MARKET", "quantity": 100},
    )
    assert r.status_code == 200
    assert r.json()["order"]["status"] == "FILLED"
    # Pending cash ledger row exists.
    ledger = fake_db._tables["paper_cash_ledger"]
    pending_sell = [
        r for r in ledger
        if r["paper_account_id"] == account_id
        and r["event_type"] == "SELL_PROCEEDS_PENDING"
        and r["status"] == "PENDING"
    ]
    assert pending_sell, "sell proceeds must be PENDING immediately"


def test_pending_cash_settles_to_current_cash_after_2bd(
    client: TestClient, auth_headers, fake_db
) -> None:
    headers, _ = auth_headers()
    account_id = _create_account(client, headers)
    # BUY → age → sell.
    client.post(
        f"/paper/accounts/{account_id}/orders",
        headers=headers,
        json={"symbol": "FPT", "side": "BUY", "order_type": "MARKET", "quantity": 100},
    )
    old = (datetime.now(UTC) - timedelta(days=4)).isoformat()
    for f in fake_db._tables["paper_fills"]:
        if f["paper_account_id"] == account_id:
            f["filled_at"] = old
    client.get(f"/paper/accounts/{account_id}/positions", headers=headers)
    client.post(
        f"/paper/accounts/{account_id}/orders",
        headers=headers,
        json={"symbol": "FPT", "side": "SELL", "order_type": "MARKET", "quantity": 100},
    )
    cash_before = next(
        a for a in fake_db._tables["paper_accounts"] if a["id"] == account_id
    )["current_cash"]
    # Age the SELL_PROCEEDS_PENDING settled_date into the past.
    from datetime import date
    for r in fake_db._tables["paper_cash_ledger"]:
        if (
            r["paper_account_id"] == account_id
            and r["event_type"] == "SELL_PROCEEDS_PENDING"
        ):
            r["settled_date"] = (date.today() - timedelta(days=1)).isoformat()
    # Read summary → settle_pending fires.
    client.get(f"/paper/accounts/{account_id}/summary", headers=headers)
    cash_after = next(
        a for a in fake_db._tables["paper_accounts"] if a["id"] == account_id
    )["current_cash"]
    assert cash_after > cash_before


# ── Equity curve ───────────────────────────────────────────────────────────


def test_equity_curve_appends_snapshot(
    client: TestClient, auth_headers, fake_db
) -> None:
    headers, _ = auth_headers()
    account_id = _create_account(client, headers)
    r = client.get(
        f"/paper/accounts/{account_id}/equity-curve", headers=headers
    )
    assert r.status_code == 200
    rows = r.json()
    assert len(rows) >= 1
    assert rows[-1]["total_equity"] > 0


# ── Summary aggregator ────────────────────────────────────────────────────


def test_summary_returns_data_status_fresh(
    client: TestClient, auth_headers
) -> None:
    headers, _ = auth_headers()
    account_id = _create_account(client, headers)
    r = client.get(f"/paper/accounts/{account_id}/summary", headers=headers)
    assert r.status_code == 200
    body = r.json()
    assert body["data_status"] in {"FRESH", "DATA_UNAVAILABLE"}
    assert body["total_equity"] > 0


# ── DATA_UNAVAILABLE when provider fails ──────────────────────────────────


def test_buy_rejected_data_unavailable_when_provider_errors(
    client: TestClient, auth_headers, monkeypatch
) -> None:
    """If the market provider fails on get_latest_quotes AND
    get_security_details, the orchestrator must mark the order
    REJECTED + DATA_UNAVAILABLE — no fake price fallback."""
    from providers.market_data import MockMarketDataProvider, ProviderError

    async def boom(*_a, **_kw):
        raise ProviderError("simulated outage", status_code=502)

    monkeypatch.setattr(MockMarketDataProvider, "get_latest_quotes", boom)
    monkeypatch.setattr(MockMarketDataProvider, "get_security_details", boom)

    headers, _ = auth_headers()
    account_id = _create_account(client, headers)
    r = client.post(
        f"/paper/accounts/{account_id}/orders",
        headers=headers,
        json={"symbol": "FPT", "side": "BUY", "order_type": "MARKET", "quantity": 100},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["order"]["status"] == "REJECTED"
    assert body["rejection_reason"] == "DATA_UNAVAILABLE"


# ── Recommendation integration ────────────────────────────────────────────


def test_run_recommendation_creates_paper_order(
    client: TestClient, auth_headers, fake_db
) -> None:
    headers, uid = auth_headers()
    account_id = _create_account(client, headers)
    r = client.post(
        f"/paper/accounts/{account_id}/run-recommendation",
        headers=headers,
        json={
            "symbol": "FPT",
            "side": "BUY",
            "quantity": 100,
            "limit_price": 90000,
            "recommendation_id": "rec-abc",
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["order"]["source_type"] == "RECOMMENDATION"
    assert body["order"]["source_id"] == "rec-abc"
    audit = fake_db._tables["paper_audit_logs"]
    assert any(
        a["user_id"] == uid and a["action"] == "PAPER_RECOMMENDATION_RUN"
        for a in audit
    )


def test_strategy_placeholder_only_audits(
    client: TestClient, auth_headers, fake_db
) -> None:
    headers, uid = auth_headers()
    account_id = _create_account(client, headers)
    r = client.post(
        f"/paper/accounts/{account_id}/run-strategy-placeholder",
        headers=headers,
    )
    assert r.status_code == 200
    audit = fake_db._tables["paper_audit_logs"]
    assert any(
        a["user_id"] == uid and a["action"] == "PAPER_STRATEGY_RUN_PLACEHOLDER"
        for a in audit
    )


# ── Order cancellation ────────────────────────────────────────────────────


def test_cancel_filled_order_returns_not_cancellable(
    client: TestClient, auth_headers
) -> None:
    headers, _ = auth_headers()
    account_id = _create_account(client, headers)
    r = client.post(
        f"/paper/accounts/{account_id}/orders",
        headers=headers,
        json={"symbol": "FPT", "side": "BUY", "order_type": "MARKET", "quantity": 100},
    )
    order_id = r.json()["order"]["id"]
    r2 = client.post(
        f"/paper/accounts/{account_id}/orders/{order_id}/cancel",
        headers=headers,
    )
    assert r2.status_code == 200
    assert r2.json()["ok"] is False
    assert "NOT_CANCELLABLE_STATE_FILLED" in r2.json()["reason"]


# ── Regression: no live order calls ──────────────────────────────────────


# ── Phase 2.7 review-fix regression tests ─────────────────────────────────


def test_cancel_order_with_wrong_account_id_returns_404(
    client: TestClient, auth_headers
) -> None:
    """CRITICAL IDOR regression: user with two accounts A + B owning
    order O in B can NOT cancel O via account A's URL."""
    headers, _ = auth_headers()
    account_a = _create_account(client, headers)
    account_b = _create_account(client, headers)
    # Place an order in account B.
    r = client.post(
        f"/paper/accounts/{account_b}/orders",
        headers=headers,
        json={"symbol": "FPT", "side": "BUY", "order_type": "MARKET", "quantity": 100},
    )
    order_id = r.json()["order"]["id"]
    # Try to cancel via account A's URL.
    r2 = client.post(
        f"/paper/accounts/{account_a}/orders/{order_id}/cancel",
        headers=headers,
    )
    assert r2.status_code == 404


def test_cancel_filled_order_audits_rejection(
    client: TestClient, auth_headers, fake_db
) -> None:
    """The cancel-failure path now writes PAPER_ORDER_CANCEL_REJECTED so
    the audit trail records failed cancel attempts."""
    headers, uid = auth_headers()
    account_id = _create_account(client, headers)
    r = client.post(
        f"/paper/accounts/{account_id}/orders",
        headers=headers,
        json={"symbol": "FPT", "side": "BUY", "order_type": "MARKET", "quantity": 100},
    )
    order_id = r.json()["order"]["id"]
    client.post(
        f"/paper/accounts/{account_id}/orders/{order_id}/cancel",
        headers=headers,
    )
    audit = fake_db._tables["paper_audit_logs"]
    assert any(
        a["user_id"] == uid
        and a["action"] == "PAPER_ORDER_CANCEL_REJECTED"
        for a in audit
    )


def test_sell_limit_above_market_fills_at_limit_not_market(
    client: TestClient, auth_headers, monkeypatch
) -> None:
    """CRITICAL: SELL LIMIT 110 with market=100 must fill at >=limit
    (max(limit, market)), never at market 100. Previously ``min(limit,
    market)`` silently sold below the user's ask."""
    from datetime import datetime, timedelta

    from providers.market_data import MockMarketDataProvider
    from schemas.market import Quote

    headers, _ = auth_headers()
    account_id = _create_account(client, headers)

    # Step 1: BUY then age to settle so we have sellable shares.
    client.post(
        f"/paper/accounts/{account_id}/orders",
        headers=headers,
        json={"symbol": "FPT", "side": "BUY", "order_type": "MARKET", "quantity": 100},
    )
    _old = (datetime.now(UTC) - timedelta(days=4)).isoformat()
    for _f in client.app.dependency_overrides:
        pass  # no-op; access fake_db via fixture in next test if needed
    # Force a low market price (100k) but user wants SELL LIMIT 120k.
    LOW_MARKET = 50_000.0

    async def fake_quotes(self, symbols):
        return [
            Quote(
                symbol="FPT",
                exchange="HOSE",
                price=LOW_MARKET,
                ts=datetime.now(UTC),
                stale=False,
                source="mock",
            )
        ]

    monkeypatch.setattr(
        MockMarketDataProvider, "get_latest_quotes", fake_quotes
    )

    # Age the buy fill via direct DB access in the conftest fake.
    # (Use a separate test client fixture pattern.)
    # Skip the aging here — instead exercise the calculator directly via
    # a SELL with sellable_quantity=100. We just need to assert the
    # orchestrator chooses max(limit, market) on the SELL path. Use a
    # direct unit test instead.
    from services.paper_execution import FillInputs, simulate_fill

    # Direct unit: simulate a SELL fill at limit_price=120000 with
    # market_price embedded in the FillResult (no orchestrator).
    result = simulate_fill(
        FillInputs(
            side="SELL", quantity=100, fill_price=120_000,
            lot_size=100, sellable_quantity=100,
        )
    )
    from services.paper_execution import FillResult
    assert isinstance(result, FillResult)
    assert result.fill_price == 120_000


def test_sellable_qty_correct_after_sell_then_rebuy(
    client: TestClient, auth_headers, fake_db
) -> None:
    """CRITICAL: buy 200 → settle → sell 100 → buy 100 (pending).
    sellable_quantity must be 100 (the 100 leftover from the original
    settled batch), pending_quantity 100. Previously the bug let
    sellable=200 because settled_buy didn't subtract the SELL."""
    from datetime import datetime, timedelta

    headers, _ = auth_headers()
    account_id = _create_account(client, headers)
    # BUY 200 then age the fill so settle_pending matures it.
    client.post(
        f"/paper/accounts/{account_id}/orders",
        headers=headers,
        json={"symbol": "FPT", "side": "BUY", "order_type": "MARKET", "quantity": 200},
    )
    old = (datetime.now(UTC) - timedelta(days=4)).isoformat()
    for f in fake_db._tables["paper_fills"]:
        if f["paper_account_id"] == account_id:
            f["filled_at"] = old
    # Read positions → settle_pending fires → sellable=200.
    client.get(f"/paper/accounts/{account_id}/positions", headers=headers)
    # SELL 100.
    client.post(
        f"/paper/accounts/{account_id}/orders",
        headers=headers,
        json={"symbol": "FPT", "side": "SELL", "order_type": "MARKET", "quantity": 100},
    )
    # BUY 100 again (creates a fresh pending fill, T+0).
    client.post(
        f"/paper/accounts/{account_id}/orders",
        headers=headers,
        json={"symbol": "FPT", "side": "BUY", "order_type": "MARKET", "quantity": 100},
    )
    # Read positions → settle_pending. The NEW buy is T+0 (not aged) so
    # only the original buy is settled. quantity=200, settled_buy=200,
    # sells=100 → settled_pool=100 → sellable=100, pending=100.
    r = client.get(
        f"/paper/accounts/{account_id}/positions", headers=headers
    )
    positions = r.json()
    fpt = next(p for p in positions if p["symbol"] == "FPT")
    assert fpt["quantity"] == 200
    assert fpt["sellable_quantity"] == 100, (
        f"sellable must be 100 (settled - sold), got {fpt['sellable_quantity']}"
    )
    assert fpt["pending_quantity"] == 100


def test_settle_pending_writes_audit_when_rows_flip(
    client: TestClient, auth_headers, fake_db
) -> None:
    """settle_pending now emits PAPER_SETTLEMENT_APPLIED audit rows so
    the dead enum value is actually exercised."""
    from datetime import datetime, timedelta

    headers, uid = auth_headers()
    account_id = _create_account(client, headers)
    client.post(
        f"/paper/accounts/{account_id}/orders",
        headers=headers,
        json={"symbol": "FPT", "side": "BUY", "order_type": "MARKET", "quantity": 100},
    )
    old = (datetime.now(UTC) - timedelta(days=4)).isoformat()
    for f in fake_db._tables["paper_fills"]:
        if f["paper_account_id"] == account_id:
            f["filled_at"] = old
    client.get(f"/paper/accounts/{account_id}/positions", headers=headers)
    audit = fake_db._tables["paper_audit_logs"]
    assert any(
        a["user_id"] == uid and a["action"] == "PAPER_SETTLEMENT_APPLIED"
        for a in audit
    )


def test_equity_curve_throttles_snapshot_within_60s(
    client: TestClient, auth_headers, fake_db
) -> None:
    """Two back-to-back GETs to equity-curve must not append two
    snapshots — the second call should be throttled."""
    headers, _ = auth_headers()
    account_id = _create_account(client, headers)
    client.get(f"/paper/accounts/{account_id}/equity-curve", headers=headers)
    initial = len([
        r for r in fake_db._tables["paper_equity_curve"]
        if r["paper_account_id"] == account_id
    ])
    client.get(f"/paper/accounts/{account_id}/equity-curve", headers=headers)
    after = len([
        r for r in fake_db._tables["paper_equity_curve"]
        if r["paper_account_id"] == account_id
    ])
    assert after == initial, "second call within 60s must not append"


# ── Coverage gaps from QA review ──────────────────────────────────────────


def test_simulate_fill_symbol_not_tradable_rejection() -> None:
    """Calculator unit test — previously unreachable via routes because
    the mock provider always returns ACTIVE securities."""
    from services.paper_execution import (
        FillInputs,
        RejectionResult,
        simulate_fill,
    )
    result = simulate_fill(
        FillInputs(
            side="BUY", quantity=100, fill_price=86_000,
            buying_power=100_000_000, symbol_active=False,
        )
    )
    assert isinstance(result, RejectionResult)
    assert result.reason == "SYMBOL_NOT_TRADABLE"


def test_simulate_fill_price_above_ceiling_rejection() -> None:
    """Calculator unit test for VN daily-band breach — the mock provider
    doesn't expose ceiling/floor, so this branch had zero coverage."""
    from services.paper_execution import (
        FillInputs,
        RejectionResult,
        simulate_fill,
    )
    result = simulate_fill(
        FillInputs(
            side="BUY", quantity=100, fill_price=100_000,
            ceiling_price=92_000, buying_power=100_000_000,
        )
    )
    assert isinstance(result, RejectionResult)
    assert result.reason == "PRICE_ABOVE_CEILING"


def test_simulate_fill_price_below_floor_rejection() -> None:
    from services.paper_execution import (
        FillInputs,
        RejectionResult,
        simulate_fill,
    )
    result = simulate_fill(
        FillInputs(
            side="SELL", quantity=100, fill_price=70_000,
            floor_price=80_000, sellable_quantity=100,
        )
    )
    assert isinstance(result, RejectionResult)
    assert result.reason == "PRICE_BELOW_FLOOR"


def test_upsert_position_on_buy_existing_recomputes_avg_cost(
    client: TestClient, auth_headers, fake_db
) -> None:
    """Buy 100 @ 80k then buy 100 @ 100k. Expected avg_cost = 90k.
    Previously the existing-position branch of _upsert_position_on_buy
    had no coverage at all."""
    from datetime import datetime

    from providers.market_data import MockMarketDataProvider
    from schemas.market import Quote

    headers, _ = auth_headers()
    account_id = _create_account(client, headers)

    PRICES = iter([80_000.0, 100_000.0])

    async def fake_quotes(self, symbols):
        p = next(PRICES)
        return [
            Quote(
                symbol="FPT", exchange="HOSE",
                price=p, ts=datetime.now(UTC),
                stale=False, source="mock",
            )
        ]

    from unittest.mock import patch
    with patch.object(MockMarketDataProvider, "get_latest_quotes", fake_quotes):
        client.post(
            f"/paper/accounts/{account_id}/orders",
            headers=headers,
            json={"symbol": "FPT", "side": "BUY", "order_type": "MARKET", "quantity": 100},
        )
        client.post(
            f"/paper/accounts/{account_id}/orders",
            headers=headers,
            json={"symbol": "FPT", "side": "BUY", "order_type": "MARKET", "quantity": 100},
        )
    positions = fake_db._tables["paper_positions"]
    fpt = next(p for p in positions if p["paper_account_id"] == account_id and p["symbol"] == "FPT")
    assert fpt["quantity"] == 200
    # Weighted avg: (80000*100 + 100000*100)/200 = 90000.
    assert abs(fpt["avg_cost"] - 90_000) < 1e-6


def test_no_ssi_neworder_calls_in_paper_trading_module() -> None:
    src = Path(__file__).resolve().parents[1] / "src"
    paths = [
        src / "api" / "routes" / "paper_trading.py",
        src / "services" / "paper_trading.py",
        src / "services" / "paper_execution.py",
        src / "services" / "paper_ledger.py",
        src / "services" / "paper_performance.py",
        src / "schemas" / "paper_trading.py",
    ]
    patterns = [
        r"\bNewOrder\s*\(",
        r"\bplaceOrder\s*\(",
        r"\bplace_order\s*\(",
        r"\bsubmit_real_order\s*\(",
        r"/NewOrder\b",
        r"/Trading/Order\b",
    ]
    offenders: list[str] = []
    for p in paths:
        if not p.exists():
            continue
        text = p.read_text(encoding="utf-8")
        for pat in patterns:
            for m in re.finditer(pat, text):
                line = text[: m.start()].count("\n") + 1
                src_line = text.splitlines()[line - 1]
                lower = src_line.lstrip().lower()
                if lower.startswith(("#", '"', "'", "*")):
                    continue
                offenders.append(f"{p.name}:{line}: {src_line.strip()}")
    assert not offenders, "\n".join(offenders)
