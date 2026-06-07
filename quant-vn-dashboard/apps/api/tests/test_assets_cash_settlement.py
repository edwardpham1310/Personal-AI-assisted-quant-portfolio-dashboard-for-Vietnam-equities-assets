"""Assets cash-movements + settlement (Phase 2.6).

Pure derivations + route round-trips. Read-only; no trading paths.
"""

from __future__ import annotations

from datetime import date

from fastapi.testclient import TestClient

from services.portfolio_valuation import build_cash_movements, build_settlement_alerts


def _t(side, qty, price, td, *, sd=None, brokerage=0.0, sell_tax=0.0, symbol="FPT"):
    return {
        "symbol": symbol, "side": side, "quantity": qty, "price": price,
        "trade_date": td, "settlement_date": sd,
        "brokerage_fee": brokerage, "sell_tax": sell_tax,
    }


# ── Pure: cash movements ────────────────────────────────────────────────────


def test_cash_movements_signs_fees_and_ascending() -> None:
    trades = [
        _t("SELL", 10, 100, "2026-02-01", brokerage=5, sell_tax=2),
        _t("BUY", 10, 100, "2026-01-01", brokerage=5),
    ]
    m = build_cash_movements(trades)
    assert [x.date for x in m] == ["2026-01-01", "2026-02-01"]  # ascending
    assert m[0].side == "BUY" and m[0].amount == -(1000 + 5)  # cash out incl fees
    assert m[1].side == "SELL" and m[1].amount == (1000 - 7)  # cash in net of fees+tax


def test_cash_movements_date_filter_inclusive() -> None:
    trades = [_t("BUY", 1, 100, "2026-01-01"), _t("BUY", 1, 100, "2026-03-01")]
    assert [x.date for x in build_cash_movements(trades, start="2026-02-01")] == ["2026-03-01"]
    assert [x.date for x in build_cash_movements(trades, end="2026-02-01")] == ["2026-01-01"]


# ── Pure: settlement alerts ─────────────────────────────────────────────────


def test_settlement_pending_only_with_kind_and_days() -> None:
    today = date(2026, 6, 1)
    trades = [
        _t("SELL", 10, 100, "2026-05-30", sd="2026-06-03", brokerage=3, sell_tax=2),
        _t("BUY", 5, 50, "2026-05-20", sd="2026-05-22"),  # already settled (past)
    ]
    a = build_settlement_alerts(trades, today=today)
    assert len(a) == 1
    assert a[0].kind == "CASH_IN"
    assert a[0].days_until == 2
    assert a[0].amount == 1000 - 5  # proceeds net of fees+tax


def test_settlement_buy_is_shares_in_no_cash() -> None:
    today = date(2026, 6, 1)
    a = build_settlement_alerts([_t("BUY", 10, 100, "2026-06-01", sd="2026-06-03")], today=today)
    assert a[0].kind == "SHARES_IN"
    assert a[0].amount is None
    assert a[0].quantity == 10


# ── Routes ──────────────────────────────────────────────────────────────────


def test_cash_movements_and_settlement_require_auth(client: TestClient) -> None:
    assert client.get("/assets/cash-movements").status_code == 401
    assert client.get("/assets/settlement").status_code == 401


def test_empty_account_returns_stable_shapes(client: TestClient, auth_headers) -> None:
    headers, _ = auth_headers()
    cm = client.get("/assets/cash-movements", headers=headers).json()
    assert cm["movements"] == [] and cm["net_cash_flow"] == 0
    st = client.get("/assets/settlement", headers=headers).json()
    assert st["alerts"] == [] and st["pending_count"] == 0


def test_cash_movements_route_with_trades(client: TestClient, auth_headers, fake_db) -> None:
    headers, _ = auth_headers()
    client.post(
        "/portfolio/positions", headers=headers,
        json={"symbol": "FPT", "quantity": 100, "avg_cost": 50.0},
    )
    acct = fake_db._tables["manual_portfolio_accounts"][0]["id"]
    fake_db._tables.setdefault("trade_transactions", []).extend([
        {"account_id": acct, "symbol": "FPT", "side": "SELL", "quantity": 60,
         "price": 70.0, "trade_date": "2026-05-05", "brokerage_fee": 50, "sell_tax": 30},
        {"account_id": acct, "symbol": "FPT", "side": "BUY", "quantity": 100,
         "price": 50.0, "trade_date": "2026-05-01", "brokerage_fee": 100},
    ])
    body = client.get("/assets/cash-movements", headers=headers).json()
    assert [m["date"] for m in body["movements"]] == ["2026-05-01", "2026-05-05"]  # ascending
    assert body["movements"][0]["amount"] == -(5000 + 100)
    assert body["net_cash_flow"] == body["movements"][0]["amount"] + body["movements"][1]["amount"]


def test_settlement_route_lists_future_pending(client: TestClient, auth_headers, fake_db) -> None:
    headers, _ = auth_headers()
    client.post(
        "/portfolio/positions", headers=headers,
        json={"symbol": "FPT", "quantity": 100, "avg_cost": 50.0},
    )
    acct = fake_db._tables["manual_portfolio_accounts"][0]["id"]
    fake_db._tables.setdefault("trade_transactions", []).extend([
        {"account_id": acct, "symbol": "FPT", "side": "SELL", "quantity": 10,
         "price": 100.0, "trade_date": "2020-01-01", "settlement_date": "2099-01-05"},
        {"account_id": acct, "symbol": "MWG", "side": "BUY", "quantity": 5,
         "price": 50.0, "trade_date": "2020-01-01", "settlement_date": "2000-01-01"},  # past
    ])
    body = client.get("/assets/settlement", headers=headers).json()
    assert body["pending_count"] == 1
    assert body["alerts"][0]["symbol"] == "FPT"
    assert body["alerts"][0]["kind"] == "CASH_IN"
