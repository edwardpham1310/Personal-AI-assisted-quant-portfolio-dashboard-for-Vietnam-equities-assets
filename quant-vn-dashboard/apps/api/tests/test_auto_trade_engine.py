"""Phase 2.9 guarded auto-trading engine tests.

Per AC checklist:
- cannot start live auto by default
- cannot start without auto-trade mode set
- cannot start if account doesn't belong to user
- cannot place order if data stale
- cannot place duplicate order during cooldown
- PAPER_ONLY creates paper order
- LIVE_MANUAL_CONFIRM creates DRAFT intent only
- LIVE_AUTO dry-run does NOT call provider.submit_order
- LIVE_AUTO all-gates-open calls provider (which 501s)
- emergency-stop / kill switch blocks future ticks
- worker endpoint requires WORKER_ENABLED flag
- worker endpoint optional secret enforced
- audit logs written for every engine action
- cross-user isolation
- default safe flags
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

# ── Test fixtures ─────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _mock_cash_for_any_account(monkeypatch: pytest.MonkeyPatch) -> None:
    """Same workaround as Phase 2.8 — MockTradingProvider only returns
    cash for ACC-DEFAULT; tests register UUID accounts."""
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


def _register_account(client: TestClient, headers: dict) -> str:
    r = client.post(
        "/trading/accounts",
        headers=headers,
        json={"account_number": "1234", "broker": "SSI"},
    )
    return r.json()["id"]


def _set_mode(client, headers, account_id, mode):
    """Helper to flip the user's auto-trade mode for an account."""
    # Use the Phase 2.6 enable-* endpoints. For OFF/PAPER_ONLY we can
    # skip risk-limit validation; for LIVE_AUTO we need full setup —
    # tests opt-in by directly mutating the fake DB instead.
    if mode == "PAPER_ONLY":
        client.post(
            "/auto-trade/enable-paper",
            headers=headers, json={"account_id": account_id},
        )
    # For other modes tests mutate the fake DB directly.


def _seed_mode(fake_db, uid, account_id, mode: str) -> None:
    """Seed an auto_trade_settings row in the requested mode."""
    fake_db._tables["auto_trade_settings"].append({
        "id": f"ats-{uid[:8]}",
        "user_id": uid,
        "account_id": account_id,
        "mode": mode,
        "enabled": True,
        "max_capital_vnd": 1_000_000_000,
        "max_order_value_vnd": 50_000_000,
        "max_orders_per_day": 100,
        "max_daily_loss_vnd": 10_000_000,
        "max_position_weight": 0.5,
        "max_sector_weight": 0.5,
        "allowed_strategies": [],
        "allowed_symbols": [],
        "allowed_watchlists": [],
        "require_manual_confirm": True,
        "require_reauth": True,
        "last_reauth_at": None,
        "risk_acknowledged_at": None,
    })


def _seed_state(fake_db, uid, account_id, *, emergency_stopped: bool = False) -> None:
    row = {
        "id": f"asx-{uid[:8]}",
        "user_id": uid,
        "account_id": account_id,
        "mode": "PAPER_ONLY",
        "is_running": False,
        "last_started_at": None,
        "last_stopped_at": None,
        "emergency_stopped_at": (
            datetime.now(UTC).isoformat() if emergency_stopped else None
        ),
        "emergency_stop_reason": "test" if emergency_stopped else None,
    }
    fake_db._tables["auto_trade_state"].append(row)


def _start_run(client, headers, account_id, *, strategy_id="default") -> str:
    r = client.post(
        "/auto-trade/runs/start",
        headers=headers,
        json={"account_id": account_id, "strategy_id": strategy_id},
    )
    return r.json()["id"]


def _seed_paper_account(client, headers) -> None:
    """Phase 2.9 PAPER_ONLY dispatch needs a paper account on file."""
    client.post(
        "/paper/accounts",
        headers=headers,
        json={"name": "Main", "starting_cash": 100_000_000, "currency": "VND"},
    )


# ── Auth gating ───────────────────────────────────────────────────────────


def test_engine_routes_require_auth(client: TestClient) -> None:
    assert client.get("/auto-trade/runs").status_code == 401
    assert client.post(
        "/auto-trade/runs/start",
        json={"account_id": "x", "strategy_id": "y"},
    ).status_code == 401
    assert client.post("/auto-trade/runs/stop?run_id=x").status_code == 401
    assert client.post("/auto-trade/runs/pause?run_id=x").status_code == 401
    assert client.get("/auto-trade/decisions").status_code == 401
    assert client.get("/auto-trade/orders").status_code == 401
    assert client.get("/auto-trade/risk-counters").status_code == 401
    assert client.post(
        "/auto-trade/worker/tick",
        json={"run_id": "x", "candidates": []},
    ).status_code == 401


# ── Start-run guards ──────────────────────────────────────────────────────


def test_start_run_refuses_when_mode_is_off(client: TestClient, auth_headers) -> None:
    headers, _ = auth_headers()
    account_id = _register_account(client, headers)
    # No mode set → auto_trade_settings.mode defaults to OFF on first read.
    r = client.post(
        "/auto-trade/runs/start",
        headers=headers,
        json={"account_id": account_id, "strategy_id": "default"},
    )
    assert r.status_code == 400
    assert "OFF" in r.json()["detail"]


def test_start_run_refuses_for_other_users_account(
    client: TestClient, auth_headers
) -> None:
    headers_a, _ = auth_headers()
    headers_b, _ = auth_headers()
    account_a = _register_account(client, headers_a)
    r = client.post(
        "/auto-trade/runs/start",
        headers=headers_b,
        json={"account_id": account_a, "strategy_id": "default"},
    )
    assert r.status_code == 404


def test_start_run_paper_only_succeeds(
    client: TestClient, auth_headers, fake_db
) -> None:
    headers, uid = auth_headers()
    account_id = _register_account(client, headers)
    _seed_mode(fake_db, uid, account_id, "PAPER_ONLY")
    r = client.post(
        "/auto-trade/runs/start",
        headers=headers,
        json={"account_id": account_id, "strategy_id": "default"},
    )
    assert r.status_code == 201
    assert r.json()["status"] == "RUNNING"
    assert r.json()["mode"] == "PAPER_ONLY"
    # Audit row.
    audit = fake_db._tables["trading_audit_logs"]
    assert any(
        a["user_id"] == uid and a["action"] == "AUTO_TRADE_RUN_STARTED"
        for a in audit
    )


# ── Worker tick gate ──────────────────────────────────────────────────────


def test_worker_tick_blocked_when_worker_disabled(
    client: TestClient, auth_headers, fake_db
) -> None:
    """AUTO_TRADE_WORKER_ENABLED defaults to false. The tick endpoint
    must 503 + audit."""
    headers, uid = auth_headers()
    r = client.post(
        "/auto-trade/worker/tick",
        headers=headers,
        json={"run_id": "x", "candidates": []},
    )
    assert r.status_code == 503
    audit = fake_db._tables["trading_audit_logs"]
    assert any(
        a["user_id"] == uid
        and a["action"] == "AUTO_TRADE_WORKER_TICK_BLOCKED"
        and a.get("metadata", {}).get("reason") == "WORKER_DISABLED"
        for a in audit
    )


def test_worker_secret_required_when_set(
    client: TestClient, auth_headers, monkeypatch, fake_db
) -> None:
    """When AUTO_TRADE_WORKER_SECRET is set, requests without the
    header are 401'd even though the user JWT is valid."""
    monkeypatch.setenv("AUTO_TRADE_WORKER_ENABLED", "true")
    monkeypatch.setenv("AUTO_TRADE_WORKER_SECRET", "shh-cron")
    from core.config import get_settings
    get_settings.cache_clear()

    headers, _ = auth_headers()
    _register_account(client, headers)
    r_no_secret = client.post(
        "/auto-trade/worker/tick",
        headers=headers,
        json={"run_id": "x", "candidates": []},
    )
    assert r_no_secret.status_code == 401
    # With the right header → progresses past the secret gate. Unknown
    # run_id → engine raises RuntimeError("not owned") → route converts
    # to 404 (Phase 2.9 review fix: was 502, leaking via wrong status).
    r_with_secret = client.post(
        "/auto-trade/worker/tick",
        headers={**headers, "X-Worker-Secret": "shh-cron"},
        json={"run_id": "x-not-found", "candidates": []},
    )
    assert r_with_secret.status_code == 404


# ── PAPER_ONLY dispatch ───────────────────────────────────────────────────


def test_paper_only_tick_creates_paper_order(
    client: TestClient, auth_headers, monkeypatch, fake_db
) -> None:
    monkeypatch.setenv("AUTO_TRADE_WORKER_ENABLED", "true")
    from core.config import get_settings
    get_settings.cache_clear()

    headers, uid = auth_headers()
    account_id = _register_account(client, headers)
    _seed_mode(fake_db, uid, account_id, "PAPER_ONLY")
    _seed_paper_account(client, headers)
    run_id = _start_run(client, headers, account_id)
    r = client.post(
        "/auto-trade/worker/tick",
        headers=headers,
        json={
            "run_id": run_id,
            "candidates": [
                {"symbol": "FPT", "action": "BUY", "quantity": 100,
                 "limit_price": 86000},
            ],
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["dispatched_count"] == 1
    # A paper_orders row exists.
    paper_orders = fake_db._tables["paper_orders"]
    assert any(o["source_type"] == "STRATEGY" for o in paper_orders)


# ── LIVE_MANUAL_CONFIRM dispatch ──────────────────────────────────────────


def test_live_manual_confirm_creates_draft_intent_only(
    client: TestClient, auth_headers, monkeypatch, fake_db
) -> None:
    monkeypatch.setenv("AUTO_TRADE_WORKER_ENABLED", "true")
    from core.config import get_settings
    get_settings.cache_clear()

    headers, uid = auth_headers()
    account_id = _register_account(client, headers)
    _seed_mode(fake_db, uid, account_id, "LIVE_MANUAL_CONFIRM")
    run_id = _start_run(client, headers, account_id)
    r = client.post(
        "/auto-trade/worker/tick",
        headers=headers,
        json={
            "run_id": run_id,
            "candidates": [
                {"symbol": "FPT", "action": "BUY", "quantity": 100,
                 "limit_price": 86000},
            ],
        },
    )
    assert r.status_code == 200, r.text
    # Exactly one DRAFT intent — engine must NOT submit.
    intents = fake_db._tables["live_order_intents"]
    new_drafts = [
        i for i in intents
        if i["source_type"] == "STRATEGY" and i["status"] == "DRAFT"
    ]
    assert len(new_drafts) == 1
    # No submission row.
    subs = fake_db._tables["live_order_submissions"]
    assert not subs


# ── LIVE_AUTO dry-run dispatch ────────────────────────────────────────────


def test_live_auto_dry_run_does_not_call_ssi_submit(
    client: TestClient, auth_headers, monkeypatch, fake_db
) -> None:
    monkeypatch.setenv("AUTO_TRADE_WORKER_ENABLED", "true")
    # Leave the live-execution flags OFF → dry-run path.
    from core.config import get_settings
    from core.deps import reset_trading_provider_cache
    get_settings.cache_clear()
    reset_trading_provider_cache()

    from providers.trading import MockTradingProvider
    called = {"hit": False}

    async def boom(*_a, **_kw):
        called["hit"] = True
        raise RuntimeError("submit_order must NOT be called in dry-run")

    monkeypatch.setattr(MockTradingProvider, "submit_order", boom)

    headers, uid = auth_headers()
    account_id = _register_account(client, headers)
    _seed_mode(fake_db, uid, account_id, "LIVE_AUTO")
    run_id = _start_run(client, headers, account_id)
    r = client.post(
        "/auto-trade/worker/tick",
        headers=headers,
        json={
            "run_id": run_id,
            "candidates": [
                {"symbol": "FPT", "action": "BUY", "quantity": 100,
                 "limit_price": 86000},
            ],
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert called["hit"] is False
    # Submission row marked DRY_RUN_OK.
    subs = fake_db._tables["live_order_submissions"]
    assert any(s["status"] == "DRY_RUN_OK" for s in subs)
    # Engine flagged the response as dry-run.
    assert body["is_dry_run"] is True


# ── Kill switch ───────────────────────────────────────────────────────────


def test_emergency_stop_blocks_future_ticks(
    client: TestClient, auth_headers, monkeypatch, fake_db
) -> None:
    monkeypatch.setenv("AUTO_TRADE_WORKER_ENABLED", "true")
    from core.config import get_settings
    get_settings.cache_clear()

    headers, uid = auth_headers()
    account_id = _register_account(client, headers)
    _seed_mode(fake_db, uid, account_id, "PAPER_ONLY")
    _seed_state(fake_db, uid, account_id, emergency_stopped=True)
    _seed_paper_account(client, headers)
    run_id = _start_run(client, headers, account_id)
    r = client.post(
        "/auto-trade/worker/tick",
        headers=headers,
        json={
            "run_id": run_id,
            "candidates": [
                {"symbol": "FPT", "action": "BUY", "quantity": 100,
                 "limit_price": 86000},
            ],
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["dispatched_count"] == 0
    assert body["skipped_count"] == 1
    decision = body["decisions"][0]
    assert decision["decision"] == "SKIPPED_KILL_SWITCH"


# ── Cooldown ──────────────────────────────────────────────────────────────


def test_cooldown_blocks_duplicate_same_symbol_action(
    client: TestClient, auth_headers, monkeypatch, fake_db
) -> None:
    monkeypatch.setenv("AUTO_TRADE_WORKER_ENABLED", "true")
    from core.config import get_settings
    get_settings.cache_clear()

    headers, uid = auth_headers()
    account_id = _register_account(client, headers)
    _seed_mode(fake_db, uid, account_id, "PAPER_ONLY")
    _seed_paper_account(client, headers)
    run_id = _start_run(client, headers, account_id)
    candidate = {
        "symbol": "FPT", "action": "BUY", "quantity": 100,
        "limit_price": 86000,
    }
    # First tick → dispatched.
    r1 = client.post(
        "/auto-trade/worker/tick",
        headers=headers,
        json={"run_id": run_id, "candidates": [candidate]},
    )
    assert r1.json()["dispatched_count"] == 1
    # Second tick immediately → cooldown active.
    r2 = client.post(
        "/auto-trade/worker/tick",
        headers=headers,
        json={"run_id": run_id, "candidates": [candidate]},
    )
    assert r2.json()["dispatched_count"] == 0
    assert any(
        d["decision"] == "SKIPPED_COOLDOWN" for d in r2.json()["decisions"]
    )


# ── Stale data ────────────────────────────────────────────────────────────


def test_stale_quote_skips_decision(
    client: TestClient, auth_headers, monkeypatch, fake_db
) -> None:
    monkeypatch.setenv("AUTO_TRADE_WORKER_ENABLED", "true")
    from core.config import get_settings
    get_settings.cache_clear()

    from providers.market_data import MockMarketDataProvider
    from schemas.market import Quote

    async def stale_quotes(self, symbols):
        return [
            Quote(
                symbol="FPT", exchange="HOSE", price=86000,
                ts=datetime.now(UTC),
                stale=True, source="mock",
            )
        ]

    monkeypatch.setattr(MockMarketDataProvider, "get_latest_quotes", stale_quotes)

    headers, uid = auth_headers()
    account_id = _register_account(client, headers)
    _seed_mode(fake_db, uid, account_id, "PAPER_ONLY")
    _seed_paper_account(client, headers)
    run_id = _start_run(client, headers, account_id)
    r = client.post(
        "/auto-trade/worker/tick",
        headers=headers,
        json={
            "run_id": run_id,
            "candidates": [
                {"symbol": "FPT", "action": "BUY", "quantity": 100,
                 "limit_price": 86000},
            ],
        },
    )
    body = r.json()
    assert body["dispatched_count"] == 0
    decision = body["decisions"][0]
    assert decision["decision"] == "SKIPPED_DATA_STALE"


# ── Run state machine ────────────────────────────────────────────────────


def test_stop_and_pause_runs_state_machine(
    client: TestClient, auth_headers, fake_db
) -> None:
    headers, uid = auth_headers()
    account_id = _register_account(client, headers)
    _seed_mode(fake_db, uid, account_id, "PAPER_ONLY")
    run_id = _start_run(client, headers, account_id)
    # Pause.
    r1 = client.post(
        "/auto-trade/runs/pause",
        headers=headers,
        params={"run_id": run_id},
    )
    assert r1.status_code == 200
    assert r1.json()["status"] == "PAUSED"
    # Stop from PAUSED.
    r2 = client.post(
        "/auto-trade/runs/stop",
        headers=headers,
        params={"run_id": run_id},
    )
    assert r2.status_code == 200
    assert r2.json()["status"] == "STOPPED"
    # Stop again from STOPPED → 409.
    r3 = client.post(
        "/auto-trade/runs/stop",
        headers=headers,
        params={"run_id": run_id},
    )
    assert r3.status_code == 409


# ── Cross-user isolation ─────────────────────────────────────────────────


def test_cannot_stop_other_users_run(
    client: TestClient, auth_headers, fake_db
) -> None:
    headers_a, uid_a = auth_headers()
    headers_b, _ = auth_headers()
    account_a = _register_account(client, headers_a)
    _seed_mode(fake_db, uid_a, account_a, "PAPER_ONLY")
    run_id = _start_run(client, headers_a, account_a)
    r = client.post(
        "/auto-trade/runs/stop",
        headers=headers_b,
        params={"run_id": run_id},
    )
    assert r.status_code == 404


# ── Default safe flags ───────────────────────────────────────────────────


def test_phase_2_9_default_safe_flags(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in (
        "AUTO_TRADE_DRY_RUN",
        "AUTO_TRADE_WORKER_ENABLED",
        "AUTO_TRADE_REQUIRE_MARKET_OPEN",
        "AUTO_TRADE_SYMBOL_COOLDOWN_MINUTES",
        "AUTO_TRADE_MAX_DECISIONS_PER_TICK",
        "AUTO_TRADE_WORKER_SECRET",
    ):
        monkeypatch.delenv(var, raising=False)
    from core.config import get_settings
    get_settings.cache_clear()
    s = get_settings()
    assert s.auto_trade_dry_run is True
    assert s.auto_trade_worker_enabled is False
    assert s.auto_trade_require_market_open is True
    assert s.auto_trade_symbol_cooldown_minutes == 30
    assert s.auto_trade_max_decisions_per_tick == 20
    assert s.auto_trade_worker_secret == ""


# ── Production-config guard ──────────────────────────────────────────────


def test_production_refuses_live_pair_without_worker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("CORS_ORIGINS", '["https://app.example.com"]')
    monkeypatch.setenv("SSI_USE_MOCK", "false")
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_JWT_SECRET", "x")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "x")
    monkeypatch.setenv("DATABASE_URL", "postgresql://x")
    monkeypatch.setenv("SSI_CONSUMER_ID", "x")
    monkeypatch.setenv("SSI_CONSUMER_SECRET", "x")
    monkeypatch.setenv("AUTO_TRADE_LIVE_ENABLED", "true")
    monkeypatch.setenv("AUTO_TRADE_ORDER_PLACEMENT_ENABLED", "true")
    monkeypatch.setenv("AUTO_TRADE_WORKER_ENABLED", "false")
    from core.config import get_settings
    get_settings.cache_clear()
    s = get_settings()
    with pytest.raises(RuntimeError, match="WORKER_ENABLED=false"):
        s.warn_if_missing_secrets()


def test_production_refuses_live_pair_with_dry_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("CORS_ORIGINS", '["https://app.example.com"]')
    monkeypatch.setenv("SSI_USE_MOCK", "false")
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_JWT_SECRET", "x")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "x")
    monkeypatch.setenv("DATABASE_URL", "postgresql://x")
    monkeypatch.setenv("SSI_CONSUMER_ID", "x")
    monkeypatch.setenv("SSI_CONSUMER_SECRET", "x")
    monkeypatch.setenv("AUTO_TRADE_LIVE_ENABLED", "true")
    monkeypatch.setenv("AUTO_TRADE_ORDER_PLACEMENT_ENABLED", "true")
    monkeypatch.setenv("AUTO_TRADE_WORKER_ENABLED", "true")
    monkeypatch.setenv("AUTO_TRADE_DRY_RUN", "true")
    from core.config import get_settings
    get_settings.cache_clear()
    s = get_settings()
    with pytest.raises(RuntimeError, match="DRY_RUN=true"):
        s.warn_if_missing_secrets()


# ── VN market hours ─────────────────────────────────────────────────────


# ── Phase 2.9 review-fix regression tests ───────────────────────────────


def test_worker_tick_cross_user_returns_404(
    client: TestClient, auth_headers, monkeypatch, fake_db
) -> None:
    """CRITICAL: previously a cross-user worker tick raised RuntimeError
    and the route returned 502 (wrong status code + leaked existence).
    The route now converts the orchestrator's not-owned RuntimeError
    into a clean 404."""
    monkeypatch.setenv("AUTO_TRADE_WORKER_ENABLED", "true")
    from core.config import get_settings
    get_settings.cache_clear()

    headers_a, uid_a = auth_headers()
    headers_b, _ = auth_headers()
    account_a = _register_account(client, headers_a)
    _seed_mode(fake_db, uid_a, account_a, "PAPER_ONLY")
    run_id = _start_run(client, headers_a, account_a)
    r = client.post(
        "/auto-trade/worker/tick",
        headers=headers_b,
        json={"run_id": run_id, "candidates": []},
    )
    assert r.status_code == 404


def test_max_order_value_rejection_in_engine(
    client: TestClient, auth_headers, monkeypatch, fake_db
) -> None:
    """CRITICAL: the engine now enforces max_order_value_vnd. Phase 2.8
    already enforced this for manual-confirm; Phase 2.9 engine path
    previously skipped it."""
    monkeypatch.setenv("AUTO_TRADE_WORKER_ENABLED", "true")
    from core.config import get_settings
    get_settings.cache_clear()

    headers, uid = auth_headers()
    account_id = _register_account(client, headers)
    _seed_mode(fake_db, uid, account_id, "PAPER_ONLY")
    # Force max_order_value_vnd = 1M VND.
    for s in fake_db._tables["auto_trade_settings"]:
        if s["user_id"] == uid:
            s["max_order_value_vnd"] = 1_000_000
    _seed_paper_account(client, headers)
    run_id = _start_run(client, headers, account_id)
    r = client.post(
        "/auto-trade/worker/tick",
        headers=headers,
        json={
            "run_id": run_id,
            "candidates": [
                # 100 × 86000 = 8.6M VND, way over the 1M cap.
                {"symbol": "FPT", "action": "BUY", "quantity": 100,
                 "limit_price": 86000},
            ],
        },
    )
    body = r.json()
    assert body["dispatched_count"] == 0
    assert body["skipped_count"] == 1
    decision = body["decisions"][0]
    assert any(
        "ORDER_VALUE_OVER_LIMIT" in r
        for r in decision["reason"]["reasons"]
    )


def test_per_decision_audit_row_written(
    client: TestClient, auth_headers, monkeypatch, fake_db
) -> None:
    """HIGH: the engine now emits AUTO_TRADE_DECISION_MADE (or
    AUTO_TRADE_RISK_REJECTED) per decision, closing the audit-enum
    discrepancy where these literals existed but were unemitted."""
    monkeypatch.setenv("AUTO_TRADE_WORKER_ENABLED", "true")
    from core.config import get_settings
    get_settings.cache_clear()

    headers, uid = auth_headers()
    account_id = _register_account(client, headers)
    _seed_mode(fake_db, uid, account_id, "PAPER_ONLY")
    _seed_paper_account(client, headers)
    run_id = _start_run(client, headers, account_id)
    client.post(
        "/auto-trade/worker/tick",
        headers=headers,
        json={
            "run_id": run_id,
            "candidates": [
                {"symbol": "FPT", "action": "BUY", "quantity": 100,
                 "limit_price": 86000},
            ],
        },
    )
    audit = fake_db._tables["trading_audit_logs"]
    assert any(
        a["user_id"] == uid and a["action"] == "AUTO_TRADE_DECISION_MADE"
        for a in audit
    )


def test_max_runtime_minutes_auto_stops_run(
    client: TestClient, auth_headers, monkeypatch, fake_db
) -> None:
    """HIGH: the engine now enforces AUTO_TRADE_MAX_RUNTIME_MINUTES —
    a run that's been running longer than the cap is auto-stopped
    instead of accepting new ticks."""
    monkeypatch.setenv("AUTO_TRADE_WORKER_ENABLED", "true")
    # 1-minute cap so we can age the run trivially.
    monkeypatch.setenv("AUTO_TRADE_MAX_RUNTIME_MINUTES", "1")
    from core.config import get_settings
    get_settings.cache_clear()

    headers, uid = auth_headers()
    account_id = _register_account(client, headers)
    _seed_mode(fake_db, uid, account_id, "PAPER_ONLY")
    _seed_paper_account(client, headers)
    run_id = _start_run(client, headers, account_id)
    # Age started_at by 5 minutes.
    old = (datetime.now(UTC) - timedelta(minutes=5)).isoformat()
    for r in fake_db._tables["auto_trade_runs"]:
        if r["id"] == run_id:
            r["started_at"] = old
    r = client.post(
        "/auto-trade/worker/tick",
        headers=headers,
        json={
            "run_id": run_id,
            "candidates": [
                {"symbol": "FPT", "action": "BUY", "quantity": 100,
                 "limit_price": 86000},
            ],
        },
    )
    body = r.json()
    assert body["dispatched_count"] == 0
    # Run was auto-stopped.
    for row in fake_db._tables["auto_trade_runs"]:
        if row["id"] == run_id:
            assert row["status"] == "STOPPED"
    # Audit row recorded the reason.
    audit = fake_db._tables["trading_audit_logs"]
    assert any(
        a["user_id"] == uid
        and a["action"] == "AUTO_TRADE_RUN_STOPPED"
        and a.get("metadata", {}).get("reason") == "MAX_RUNTIME_EXCEEDED"
        for a in audit
    )


def test_market_closed_skips_decision(
    client: TestClient, auth_headers, monkeypatch, fake_db
) -> None:
    """HIGH: previously untested. With require_market_open=true and the
    VN session closed, candidates are skipped with MARKET_CLOSED."""
    monkeypatch.setenv("AUTO_TRADE_WORKER_ENABLED", "true")
    monkeypatch.setenv("AUTO_TRADE_REQUIRE_MARKET_OPEN", "true")
    from core.config import get_settings
    get_settings.cache_clear()

    # We can't easily change "now", so the test depends on the test
    # running outside VN trading hours (most of the time). Use the
    # scheduler helper directly to skip the test if we happen to be
    # mid-session.
    from services.auto_trade_scheduler import vn_market_is_open
    if vn_market_is_open():
        pytest.skip("VN session currently open — cannot exercise MARKET_CLOSED")

    headers, uid = auth_headers()
    account_id = _register_account(client, headers)
    _seed_mode(fake_db, uid, account_id, "PAPER_ONLY")
    _seed_paper_account(client, headers)
    run_id = _start_run(client, headers, account_id)
    r = client.post(
        "/auto-trade/worker/tick",
        headers=headers,
        json={
            "run_id": run_id,
            "candidates": [
                {"symbol": "FPT", "action": "BUY", "quantity": 100,
                 "limit_price": 86000},
            ],
        },
    )
    body = r.json()
    assert body["dispatched_count"] == 0
    decision = body["decisions"][0]
    assert decision["decision"] == "SKIPPED_MARKET_CLOSED"


def test_max_decisions_per_tick_truncates(
    client: TestClient, auth_headers, monkeypatch, fake_db
) -> None:
    """HIGH: previously untested. AUTO_TRADE_MAX_DECISIONS_PER_TICK
    caps how many candidates are processed per tick — guard against
    a misconfigured scheduler hammering the engine."""
    monkeypatch.setenv("AUTO_TRADE_WORKER_ENABLED", "true")
    monkeypatch.setenv("AUTO_TRADE_MAX_DECISIONS_PER_TICK", "3")
    from core.config import get_settings
    get_settings.cache_clear()

    headers, uid = auth_headers()
    account_id = _register_account(client, headers)
    _seed_mode(fake_db, uid, account_id, "PAPER_ONLY")
    _seed_paper_account(client, headers)
    run_id = _start_run(client, headers, account_id)
    # 10 candidates — engine must process only 3.
    candidates = [
        {"symbol": sym, "action": "BUY", "quantity": 100, "limit_price": 86000}
        for sym in ("FPT", "MWG", "HPG", "VNM", "VCB", "VRE",
                    "ACB", "VPB", "TCB", "STB")
    ]
    r = client.post(
        "/auto-trade/worker/tick",
        headers=headers,
        json={"run_id": run_id, "candidates": candidates},
    )
    body = r.json()
    total = body["dispatched_count"] + body["skipped_count"]
    assert total <= 3, f"expected <=3 decisions, got {total}"


def test_validate_engine_decision_action_not_allowed_direct() -> None:
    """HIGH: pure-function unit test of the validator. Previously the
    validator was exercised only via the route — direct test gives a
    fast regression net for the rejection-precedence logic."""
    from core.config import Settings
    from services.auto_trade_risk import (
        EngineRiskContext,
        validate_engine_decision,
    )
    s = Settings(_env_file=None)  # type: ignore[call-arg]
    ctx = EngineRiskContext(
        settings=s,
        run_row={"status": "RUNNING", "mode": "PAPER_ONLY",
                 "account_id": "X", "id": "R"},
        user_mode="PAPER_ONLY",
        auto_trade_state_row={},
        auto_trade_settings_row={},
        candidate={"symbol": "FPT", "action": "HOLD",
                   "quantity": 100, "limit_price": 86000},
        quote=None, security=None, cash=None, position=None,
        avg_value_20d=None,
        cooldown_seconds_remaining=0,
        orders_today_count=0,
        gross_order_value_today=0,
    )
    result = validate_engine_decision(ctx)
    assert result.status == "REJECTED"
    assert any("ACTION_NOT_ALLOWED" in r for r in result.reasons)


def test_worker_secret_uses_constant_time_compare() -> None:
    """CRITICAL: pin that the route uses ``hmac.compare_digest`` for
    the worker-secret comparison. Without this, a short-enough secret
    could be brute-forced via timing side channel. We assert by
    inspecting the route source — there's no clean way to dynamic-test
    timing safety from Python."""
    from pathlib import Path
    src = Path(__file__).resolve().parents[1] / "src" / "api" / "routes" / "auto_trade.py"
    text = src.read_text(encoding="utf-8")
    assert "compare_digest" in text, (
        "Worker-secret comparison must use hmac.compare_digest, not '!='"
    )


def test_vn_market_hours_helper() -> None:
    from services.auto_trade_scheduler import vn_market_is_open

    # 02:00 UTC Wednesday = 09:00 ICT — market open.
    open_ts = datetime(2026, 5, 27, 2, 30, tzinfo=UTC)
    assert vn_market_is_open(open_ts) is True
    # 16:00 UTC Wednesday = 23:00 ICT — closed.
    closed_ts = datetime(2026, 5, 27, 16, 0, tzinfo=UTC)
    assert vn_market_is_open(closed_ts) is False
    # 05:00 UTC Saturday → weekend.
    weekend_ts = datetime(2026, 5, 30, 5, 0, tzinfo=UTC)
    assert vn_market_is_open(weekend_ts) is False
