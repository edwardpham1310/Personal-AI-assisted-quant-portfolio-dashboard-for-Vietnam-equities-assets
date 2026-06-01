"""Phase 2.8 Manual-confirm live trading tests.

Covers the AC checklist:
- cannot submit by default (all gates closed → dry run)
- cannot submit without re-auth
- cannot submit with expired preview
- cannot submit if risk validation fails (price band etc.)
- dry-run submit does NOT call SSI
- forbidden direct provider call not exposed via routes
- audit logs written for every state transition
- real submit gated by all config flags
- no auto-submit path exists
- cross-user intent access blocked
- state-machine illegal transitions blocked
"""

from __future__ import annotations

import re
from datetime import UTC
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def _mock_cash_for_any_account(monkeypatch: pytest.MonkeyPatch) -> None:
    """The MockTradingProvider only returns cash for ACC-DEFAULT. Tests
    here create real trading accounts (UUIDs) → cash=0 → preview rejects
    INSUFFICIENT_CASH and the state machine can't advance past
    PREVIEWED. Patch ``get_cash_balance`` + ``get_stock_positions`` to
    return generous defaults regardless of account_id so the safety
    logic itself is what gets tested, not fixture wiring.
    """
    from datetime import datetime as _dt

    from providers.trading import MockTradingProvider
    from schemas.trading import CashBalance

    async def fake_cash(self, account_id):
        return CashBalance(
            account_id=account_id,
            cash_balance=100_000_000,
            buying_power=100_000_000,
            withdrawable_cash=100_000_000,
            pending_cash=0,
            currency="VND",
            as_of=_dt.now(UTC),
        )

    async def fake_positions(self, account_id):
        return []

    monkeypatch.setattr(MockTradingProvider, "get_cash_balance", fake_cash)
    monkeypatch.setattr(MockTradingProvider, "get_stock_positions", fake_positions)


# ── Helpers ─────────────────────────────────────────────────────────────────


def _register_account(client: TestClient, headers: dict) -> str:
    r = client.post(
        "/trading/accounts",
        headers=headers,
        json={"account_number": "12345678", "broker": "SSI"},
    )
    return r.json()["id"]


def _create_intent(
    client: TestClient,
    headers: dict,
    account_id: str,
    *,
    side: str = "BUY",
    quantity: int = 100,
    limit_price: float = 86000,
    symbol: str = "FPT",
) -> str:
    r = client.post(
        "/trading/live-order-intents",
        headers=headers,
        json={
            "account_id": account_id,
            "symbol": symbol,
            "side": side,
            "order_type": "LIMIT",
            "quantity": quantity,
            "limit_price": limit_price,
            "source_type": "MANUAL",
        },
    )
    return r.json()["id"]


def _full_flow_to_confirmed(
    client: TestClient, headers: dict, account_id: str
) -> str:
    intent_id = _create_intent(client, headers, account_id)
    client.post(
        f"/trading/live-order-intents/{intent_id}/preview", headers=headers,
    )
    client.post(
        f"/trading/live-order-intents/{intent_id}/request-confirmation",
        headers=headers,
    )
    client.post(
        f"/trading/live-order-intents/{intent_id}/confirm",
        headers=headers,
        json={"risk_acknowledged": True},
    )
    return intent_id


# ── Auth gating ────────────────────────────────────────────────────────────


def test_live_routes_require_auth(client: TestClient) -> None:
    assert client.post("/trading/live-order-intents", json={}).status_code == 401
    assert client.get("/trading/live-order-intents").status_code == 401
    assert client.get("/trading/live-order-intents/x").status_code == 401
    assert client.post("/trading/live-order-intents/x/preview").status_code == 401
    assert client.post("/trading/live-order-intents/x/request-confirmation").status_code == 401
    assert client.post("/trading/live-order-intents/x/confirm", json={"risk_acknowledged": True}).status_code == 401
    assert client.post("/trading/live-order-intents/x/submit").status_code == 401
    assert client.post("/trading/live-order-intents/x/cancel").status_code == 401


# ── Default config: gates all closed → dry-run path ───────────────────────


def test_default_gate_status_all_closed(
    client: TestClient, auth_headers
) -> None:
    headers, _ = auth_headers()
    account_id = _register_account(client, headers)
    intent_id = _create_intent(client, headers, account_id)
    r = client.post(
        f"/trading/live-order-intents/{intent_id}/preview", headers=headers
    )
    assert r.status_code == 200, r.text
    gate = r.json()["gate_status"]
    assert gate["live_order_enabled"] is False
    assert gate["manual_confirm_enabled"] is False
    assert gate["all_open"] is False
    assert r.json()["is_dry_run"] is True


def test_full_flow_dry_run_does_not_call_ssi_submit(
    client: TestClient, auth_headers, monkeypatch, fake_db
) -> None:
    """Default config: gate closed → submit is dry-run synthetic. The
    provider's ``submit_order`` must NOT be called."""
    from providers.trading import MockTradingProvider

    called = {"hit": False}

    async def boom(*_a, **_kw):
        called["hit"] = True
        raise RuntimeError("submit_order MUST NOT be called in dry-run path")

    monkeypatch.setattr(MockTradingProvider, "submit_order", boom)

    headers, uid = auth_headers()
    account_id = _register_account(client, headers)
    intent_id = _full_flow_to_confirmed(client, headers, account_id)
    r = client.post(
        f"/trading/live-order-intents/{intent_id}/submit", headers=headers,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert called["hit"] is False
    assert body["is_live_submission_performed"] is False
    assert body["is_dry_run"] is True
    # Submission row was written with DRY_RUN_OK.
    subs = fake_db._tables["live_order_submissions"]
    matching = [s for s in subs if s["user_id"] == uid]
    assert matching
    assert matching[-1]["status"] == "DRY_RUN_OK"
    # Intent moved to SUBMITTED.
    intent = fake_db._tables["live_order_intents"][-1]
    assert intent["status"] == "SUBMITTED"


# ── State machine ─────────────────────────────────────────────────────────


def test_create_intent_starts_in_draft(
    client: TestClient, auth_headers
) -> None:
    headers, _ = auth_headers()
    account_id = _register_account(client, headers)
    intent_id = _create_intent(client, headers, account_id)
    r = client.get(
        f"/trading/live-order-intents/{intent_id}", headers=headers,
    )
    assert r.json()["status"] == "DRAFT"


def test_cannot_request_confirmation_from_draft(
    client: TestClient, auth_headers
) -> None:
    headers, _ = auth_headers()
    account_id = _register_account(client, headers)
    intent_id = _create_intent(client, headers, account_id)
    r = client.post(
        f"/trading/live-order-intents/{intent_id}/request-confirmation",
        headers=headers,
    )
    assert r.status_code == 409


def test_cannot_confirm_from_previewed(
    client: TestClient, auth_headers
) -> None:
    headers, _ = auth_headers()
    account_id = _register_account(client, headers)
    intent_id = _create_intent(client, headers, account_id)
    client.post(
        f"/trading/live-order-intents/{intent_id}/preview", headers=headers,
    )
    # Skip request-confirmation step → confirm should 409.
    r = client.post(
        f"/trading/live-order-intents/{intent_id}/confirm",
        headers=headers,
        json={"risk_acknowledged": True},
    )
    assert r.status_code == 409


def test_confirm_requires_risk_acknowledged_true(
    client: TestClient, auth_headers, fake_db
) -> None:
    headers, uid = auth_headers()
    account_id = _register_account(client, headers)
    intent_id = _create_intent(client, headers, account_id)
    client.post(
        f"/trading/live-order-intents/{intent_id}/preview", headers=headers,
    )
    client.post(
        f"/trading/live-order-intents/{intent_id}/request-confirmation",
        headers=headers,
    )
    r = client.post(
        f"/trading/live-order-intents/{intent_id}/confirm",
        headers=headers,
        json={"risk_acknowledged": False},
    )
    assert r.status_code == 400
    # Phase 2.8 review fix: confirm-step rejection now uses the
    # dedicated CONFIRM_REJECTED action so it doesn't pollute the
    # SUBMIT_REJECTED audit channel.
    audit = fake_db._tables["trading_audit_logs"]
    assert any(
        a["user_id"] == uid
        and a["action"] == "LIVE_ORDER_CONFIRM_REJECTED"
        and a.get("metadata", {}).get("reason") == "RISK_ACK_REQUIRED"
        for a in audit
    )


def test_submit_without_confirmed_returns_409(
    client: TestClient, auth_headers, fake_db
) -> None:
    """Phase 2.8 review fix (CRITICAL): submitting from any non-CONFIRMED
    state must 409 BEFORE the gauntlet runs. Previously the orchestrator
    persisted a REJECTED_BY_GATE submission row, polluting the
    daily-order ceiling and audit history with phantom rejections.
    """
    headers, uid = auth_headers()
    account_id = _register_account(client, headers)
    intent_id = _create_intent(client, headers, account_id)
    client.post(
        f"/trading/live-order-intents/{intent_id}/preview", headers=headers,
    )
    r = client.post(
        f"/trading/live-order-intents/{intent_id}/submit", headers=headers,
    )
    assert r.status_code == 409
    # No submission row written (the count would have been 1 if the
    # bug remained).
    subs = fake_db._tables["live_order_submissions"]
    assert not any(
        s["live_order_intent_id"] == intent_id for s in subs
    )
    # An audit row recording the rejection attempt is still written.
    audit = fake_db._tables["trading_audit_logs"]
    assert any(
        a["user_id"] == uid
        and a["action"] == "LIVE_ORDER_SUBMIT_REJECTED"
        and a.get("metadata", {}).get("reason") == "NOT_CONFIRMED"
        for a in audit
    )


# ── Re-auth gate ──────────────────────────────────────────────────────────


def test_submit_rejected_when_jwt_iat_stale(
    client: TestClient, auth_headers, monkeypatch, fake_db
) -> None:
    """A stale JWT iat (or 0-second window) must fail the re-auth gate."""
    headers, _ = auth_headers()
    account_id = _register_account(client, headers)
    intent_id = _full_flow_to_confirmed(client, headers, account_id)
    monkeypatch.setenv("TRADING_REAUTH_MAX_AGE_SECONDS", "0")
    from core.config import get_settings
    get_settings.cache_clear()
    r = client.post(
        f"/trading/live-order-intents/{intent_id}/submit", headers=headers,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["validation_status"] == "REJECTED"
    assert any("REAUTH_REQUIRED" in x for x in body["rejection_reasons"])


# ── Preview expiry ────────────────────────────────────────────────────────


def test_submit_rejected_when_preview_expired(
    client: TestClient, auth_headers, fake_db, monkeypatch
) -> None:
    headers, _ = auth_headers()
    account_id = _register_account(client, headers)
    intent_id = _full_flow_to_confirmed(client, headers, account_id)
    # Force ORDER_PREVIEW_MAX_AGE_SECONDS=0 so any created_at is "expired".
    monkeypatch.setenv("ORDER_PREVIEW_MAX_AGE_SECONDS", "0")
    from core.config import get_settings
    get_settings.cache_clear()
    r = client.post(
        f"/trading/live-order-intents/{intent_id}/submit", headers=headers,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["validation_status"] == "REJECTED"
    assert any("PREVIEW_EXPIRED" in x for x in body["rejection_reasons"])


# ── Cross-user isolation ──────────────────────────────────────────────────


def test_cannot_access_other_users_intent(
    client: TestClient, auth_headers
) -> None:
    headers_a, _ = auth_headers()
    headers_b, _ = auth_headers()
    account_a = _register_account(client, headers_a)
    intent_id = _create_intent(client, headers_a, account_a)
    r = client.get(
        f"/trading/live-order-intents/{intent_id}", headers=headers_b
    )
    assert r.status_code == 404


def test_cannot_submit_other_users_intent(
    client: TestClient, auth_headers
) -> None:
    headers_a, _ = auth_headers()
    headers_b, _ = auth_headers()
    account_a = _register_account(client, headers_a)
    intent_id = _full_flow_to_confirmed(client, headers_a, account_a)
    r = client.post(
        f"/trading/live-order-intents/{intent_id}/submit",
        headers=headers_b,
    )
    assert r.status_code == 404


# ── Cancel ───────────────────────────────────────────────────────────────


def test_cancel_from_draft_succeeds(client: TestClient, auth_headers) -> None:
    headers, _ = auth_headers()
    account_id = _register_account(client, headers)
    intent_id = _create_intent(client, headers, account_id)
    r = client.post(
        f"/trading/live-order-intents/{intent_id}/cancel", headers=headers,
    )
    assert r.status_code == 200
    assert r.json()["intent"]["status"] == "CANCELLED"


def test_cancel_terminal_state_returns_409(
    client: TestClient, auth_headers
) -> None:
    headers, _ = auth_headers()
    account_id = _register_account(client, headers)
    intent_id = _full_flow_to_confirmed(client, headers, account_id)
    # Submit → SUBMITTED (terminal).
    client.post(
        f"/trading/live-order-intents/{intent_id}/submit", headers=headers,
    )
    r = client.post(
        f"/trading/live-order-intents/{intent_id}/cancel", headers=headers,
    )
    assert r.status_code == 409


# ── Audit log coverage ──────────────────────────────────────────────────


def test_full_dry_run_writes_audit_chain(
    client: TestClient, auth_headers, fake_db
) -> None:
    headers, uid = auth_headers()
    account_id = _register_account(client, headers)
    intent_id = _full_flow_to_confirmed(client, headers, account_id)
    client.post(
        f"/trading/live-order-intents/{intent_id}/submit", headers=headers,
    )
    actions = [
        a["action"] for a in fake_db._tables["trading_audit_logs"]
        if a["user_id"] == uid
    ]
    for required in (
        "LIVE_ORDER_INTENT_CREATED",
        "LIVE_ORDER_PREVIEWED",
        "LIVE_ORDER_CONFIRMATION_REQUESTED",
        "LIVE_ORDER_CONFIRMED",
        "LIVE_ORDER_SUBMIT_ATTEMPTED",
        "LIVE_ORDER_SUBMIT_DRY_RUN_OK",
    ):
        assert required in actions, f"missing audit {required}"


# ── Live gate: when ALL flags open, provider 501 surfaces as FAILED ────────


def test_all_gates_open_calls_provider_which_raises_501(
    client: TestClient, auth_headers, monkeypatch, fake_db
) -> None:
    """When all 5 flags align AND the per-account trading_enabled is
    true, the orchestrator calls the provider's submit_order. The Mock
    provider (and real SSI provider) both raise NOT_IMPLEMENTED in
    Phase 2.8 — the intent should land in FAILED, NOT silently succeed.
    """
    monkeypatch.setenv("TRADING_LIVE_ORDER_ENABLED", "true")
    monkeypatch.setenv("TRADING_MANUAL_CONFIRM_ENABLED", "true")
    monkeypatch.setenv("SSI_TRADING_READ_ONLY", "false")
    monkeypatch.setenv("SSI_TRADING_USE_MOCK", "false")
    monkeypatch.setenv("TRADING_ORDER_PLACEMENT_DRY_RUN", "false")
    # Need real SSI creds so SSITradingProvider can be instantiated.
    monkeypatch.setenv("SSI_TRADING_CONSUMER_ID", "x")
    monkeypatch.setenv("SSI_TRADING_CONSUMER_SECRET", "y")
    from core.config import get_settings
    from core.deps import reset_trading_provider_cache
    get_settings.cache_clear()
    reset_trading_provider_cache()

    headers, _ = auth_headers()
    account_id = _register_account(client, headers)
    # Phase 2.8 review fix: enable trading on the account. No public
    # route flips this yet (Phase 2.9 will add one); seed via the fake
    # DB directly so we can exercise the live path.
    for acc in fake_db._tables["trading_accounts"]:
        if acc["id"] == account_id:
            acc["trading_enabled"] = True
    intent_id = _full_flow_to_confirmed(client, headers, account_id)
    r = client.post(
        f"/trading/live-order-intents/{intent_id}/submit", headers=headers,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    # Phase 2.8: provider 501s → intent FAILED, not SUBMITTED.
    assert body["intent"]["status"] == "FAILED"
    assert body["is_live_submission_performed"] is False
    assert any("BROKER_ERROR" in x for x in body["rejection_reasons"])


def test_provider_status_reports_not_implemented_for_ssi_submit() -> None:
    """The SSI provider's submit_order method exists but raises 501. This
    pins the contract: Phase 2.8 scaffold only, no real HTTP yet."""
    import asyncio

    from providers.trading import SSITradingProvider
    from providers.trading.base import TradingProviderError

    p = SSITradingProvider(
        consumer_id="id", consumer_secret="secret",
        base_url="https://fc-tradeapi.ssi.com.vn", timeout=5.0,
    )

    async def _call():
        await p.submit_order(
            account_id="x", symbol="FPT", side="BUY",
            order_type="LIMIT", quantity=100, limit_price=86000,
        )

    with pytest.raises(TradingProviderError) as exc:
        asyncio.run(_call())
    assert exc.value.status_code == 501


# ── No-auto-submit regression sweep ───────────────────────────────────────


# ── Phase 2.8 review-fix regression tests ────────────────────────────────


def test_mock_provider_submit_order_raises_501() -> None:
    """MockTradingProvider's submit_order must raise 501. Without this
    contract, a future refactor that lets the mock return a synthetic
    fill would silently bypass every Phase 2.8 safety gate."""
    import asyncio

    from providers.trading import MockTradingProvider
    from providers.trading.base import TradingProviderError

    p = MockTradingProvider()
    async def _call():
        await p.submit_order(
            account_id="x", symbol="FPT", side="BUY",
            order_type="LIMIT", quantity=100, limit_price=86000,
        )
    with pytest.raises(TradingProviderError) as exc:
        asyncio.run(_call())
    assert exc.value.status_code == 501


def test_phase_2_8_default_safe_flags(monkeypatch: pytest.MonkeyPatch) -> None:
    """All five Phase 2.8 flags must default to the safe values when no
    env vars are set. Same pattern as Phase 2.6's default-safe-flags
    test — pins the defaults so a typo in config.py can't ship a
    live-enabled build."""
    for var in (
        "TRADING_LIVE_ORDER_ENABLED",
        "TRADING_MANUAL_CONFIRM_ENABLED",
        "TRADING_REQUIRE_REAUTH",
        "TRADING_REAUTH_MAX_AGE_SECONDS",
        "TRADING_ORDER_PLACEMENT_DRY_RUN",
        "ORDER_PREVIEW_MAX_AGE_SECONDS",
    ):
        monkeypatch.delenv(var, raising=False)
    from core.config import get_settings
    get_settings.cache_clear()
    s = get_settings()
    assert s.trading_live_order_enabled is False
    assert s.trading_manual_confirm_enabled is False
    assert s.trading_require_reauth is True
    assert s.trading_reauth_max_age_seconds == 300
    assert s.trading_order_placement_dry_run is True
    assert s.order_preview_max_age_seconds == 60


def test_auto_trade_live_auto_forbidden_in_revalidate(
    client: TestClient, auth_headers, fake_db
) -> None:
    """The Phase 2.8 premise is manual-only. A user whose auto_trade
    mode is LIVE_AUTO must NOT be able to submit a live order through
    the manual-confirm scaffold — the orchestrator rejects with
    AUTO_TRADE_LIVE_AUTO_FORBIDDEN.

    Previously this rule had zero direct coverage."""
    headers, uid = auth_headers()
    account_id = _register_account(client, headers)
    intent_id = _full_flow_to_confirmed(client, headers, account_id)
    # Force the user's auto_trade_settings row into LIVE_AUTO mode by
    # mutating the fake DB directly (no public API to flip it without
    # a multi-step Phase 2.6 flow).
    fake_db._tables["auto_trade_settings"].append({
        "id": "ats-1",
        "user_id": uid,
        "account_id": account_id,
        "mode": "LIVE_AUTO",
        "enabled": True,
        "max_capital_vnd": 0,
        "max_order_value_vnd": 0,
        "max_orders_per_day": 0,
        "max_daily_loss_vnd": 0,
        "max_position_weight": 0,
        "max_sector_weight": 0,
        "allowed_strategies": [],
        "allowed_symbols": [],
        "allowed_watchlists": [],
        "require_manual_confirm": True,
        "require_reauth": True,
        "last_reauth_at": None,
        "risk_acknowledged_at": None,
    })
    r = client.post(
        f"/trading/live-order-intents/{intent_id}/submit", headers=headers,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["validation_status"] == "REJECTED"
    assert any(
        "AUTO_TRADE_LIVE_AUTO_FORBIDDEN" in x
        for x in body["rejection_reasons"]
    )


def test_submit_rejected_when_quote_stale(
    client: TestClient, auth_headers, monkeypatch
) -> None:
    """Phase 2.8 review fix: a non-None but stale quote must trigger
    QUOTE_STALE rejection. AC item 13 requires data freshness be
    enforced — previously only ``quote is None`` was checked."""
    from datetime import datetime as _dt

    from providers.market_data import MockMarketDataProvider
    from schemas.market import Quote

    async def stale_quotes(self, symbols):
        return [
            Quote(
                symbol="FPT", exchange="HOSE",
                price=86000, ts=_dt.now(UTC),
                stale=True, source="mock",
            )
        ]

    monkeypatch.setattr(
        MockMarketDataProvider, "get_latest_quotes", stale_quotes
    )

    headers, _ = auth_headers()
    account_id = _register_account(client, headers)
    intent_id = _full_flow_to_confirmed(client, headers, account_id)
    r = client.post(
        f"/trading/live-order-intents/{intent_id}/submit", headers=headers,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["validation_status"] == "REJECTED"
    assert any("QUOTE_STALE" in x for x in body["rejection_reasons"])


def test_orders_today_fail_closed_on_unparseable_timestamp(
    client: TestClient, auth_headers, fake_db
) -> None:
    """An attacker who poisons ``submitted_at`` to an unparseable
    string previously bypassed the daily-order ceiling (the parse
    error was silently dropped). Fix: unparseable rows count toward
    the limit."""
    import asyncio

    from api.routes.trading import _orders_today_for

    headers, uid = auth_headers()
    account_id = _register_account(client, headers)
    # Insert a poisoned submission row directly.
    fake_db._tables["live_order_submissions"].append({
        "id": "sub-poison",
        "user_id": uid,
        "account_id": account_id,
        "live_order_intent_id": "x",
        "broker": "SSI",
        "request_payload_sanitized": {},
        "response_payload_sanitized": {},
        "status": "REJECTED_BY_GATE",
        "submitted_at": "NOT_A_TIMESTAMP",
        "created_at": "NOT_A_TIMESTAMP",
    })

    class _U:
        user_id = uid
        raw_token = ""
    # We need a real auth token for the fake DB's user_jwt path —
    # reuse the auth_headers helper.
    headers2, _ = auth_headers(user_id=uid)

    # Cheat: monkey-construct the AuthContext with the issued token.
    token = headers2["Authorization"].split(" ", 1)[1]

    class _UReal:
        user_id = uid
        raw_token = token

    count = asyncio.run(_orders_today_for(fake_db, _UReal(), account_id))
    # Poisoned row counted (fail-closed).
    assert count >= 1


def test_transition_or_404_rejects_concurrent_state_change(
    client: TestClient, auth_headers, fake_db
) -> None:
    """Phase 2.8 review fix (HIGH TOCTOU): _transition_or_404 now
    includes ``status=current`` in the WHERE clause. If the row has
    already moved on (e.g. cancelled concurrently), the route returns
    409 instead of silently overwriting."""
    headers, _ = auth_headers()
    account_id = _register_account(client, headers)
    intent_id = _create_intent(client, headers, account_id)
    # Race: cancel first.
    client.post(
        f"/trading/live-order-intents/{intent_id}/cancel", headers=headers,
    )
    # Now try to preview on the cancelled intent.
    r = client.post(
        f"/trading/live-order-intents/{intent_id}/preview", headers=headers,
    )
    assert r.status_code == 409


def test_account_not_live_enabled_rejection(
    client: TestClient, auth_headers, monkeypatch, fake_db
) -> None:
    """When the 5-flag env gate is open but the per-account
    ``trading_accounts.trading_enabled`` is false (Phase 2.5 default),
    the live path must REJECT with ACCOUNT_NOT_LIVE_ENABLED — NOT
    fall through to the provider."""
    monkeypatch.setenv("TRADING_LIVE_ORDER_ENABLED", "true")
    monkeypatch.setenv("TRADING_MANUAL_CONFIRM_ENABLED", "true")
    monkeypatch.setenv("SSI_TRADING_READ_ONLY", "false")
    monkeypatch.setenv("SSI_TRADING_USE_MOCK", "false")
    monkeypatch.setenv("TRADING_ORDER_PLACEMENT_DRY_RUN", "false")
    monkeypatch.setenv("SSI_TRADING_CONSUMER_ID", "x")
    monkeypatch.setenv("SSI_TRADING_CONSUMER_SECRET", "y")
    from core.config import get_settings
    from core.deps import reset_trading_provider_cache
    get_settings.cache_clear()
    reset_trading_provider_cache()

    headers, _ = auth_headers()
    account_id = _register_account(client, headers)
    # Deliberately leave trading_enabled=False.
    intent_id = _full_flow_to_confirmed(client, headers, account_id)
    r = client.post(
        f"/trading/live-order-intents/{intent_id}/submit", headers=headers,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["validation_status"] == "REJECTED"
    assert "ACCOUNT_NOT_LIVE_ENABLED" in body["rejection_reasons"]
    assert body["is_live_submission_performed"] is False


def test_no_background_submit_path_exists() -> None:
    """The Phase 2.8 module must not contain a background submit
    helper / scheduler / worker that could call ``submit_order``
    without an HTTP request from the user."""
    src = Path(__file__).resolve().parents[1] / "src"
    forbidden_patterns = [
        r"asyncio\.create_task\([^)]*submit_order",
        r"BackgroundTasks.*submit_order",
        r"scheduler\.\w+.*submit_order",
        r"celery.*submit_order",
    ]
    offenders: list[str] = []
    for py in src.rglob("*.py"):
        text = py.read_text(encoding="utf-8")
        for pat in forbidden_patterns:
            for m in re.finditer(pat, text):
                line = text[: m.start()].count("\n") + 1
                offenders.append(f"{py.relative_to(src)}:{line}")
    assert not offenders, "background submit path found: " + ", ".join(offenders)
