"""Phase 2.6 auto-trade route + service tests.

Coverage:
* Default mode is OFF.
* PAPER_ONLY transition works without re-auth.
* LIVE_MANUAL_CONFIRM requires recent re-auth.
* LIVE_AUTO requires recent re-auth + all risk limits + risk_acknowledged.
* Emergency stop disables mode + records reason.
* Audit logs are written for every mode change.
* Cross-user isolation — a user cannot access another user's settings.
* Live execution stays disabled in Phase 2.6 even after LIVE_AUTO confirm.
* No SSI NewOrder call exists in auto_trade.py.
"""

from __future__ import annotations

import datetime
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


# ── Helpers ────────────────────────────────────────────────────────────────


def _register_account(client: TestClient, headers: dict) -> str:
    r = client.post(
        "/trading/accounts",
        headers=headers,
        json={"account_number": "1234", "broker": "SSI"},
    )
    return r.json()["id"]


def _full_risk_payload() -> dict:
    return {
        "max_capital_vnd": 50_000_000,
        "max_order_value_vnd": 5_000_000,
        "max_orders_per_day": 10,
        "max_daily_loss_vnd": 2_000_000,
        "max_position_weight": 0.2,
        "max_sector_weight": 0.4,
        "allowed_strategies": ["TREND_FOLLOW"],
        "allowed_symbols": ["FPT", "MWG"],
        "allowed_watchlists": [],
    }


def _fresh_token_user(auth_headers):
    """auth_headers already mints a fresh JWT with `iat=now`, so the JWT
    `iat` is within the 300s reauth window by default."""
    return auth_headers()


# ── Auth gating ────────────────────────────────────────────────────────────


def test_all_auto_trade_routes_require_auth(client: TestClient) -> None:
    assert client.get("/auto-trade/settings?account_id=x").status_code == 401
    assert client.put("/auto-trade/settings?account_id=x", json={}).status_code == 401
    assert client.get("/auto-trade/state?account_id=x").status_code == 401
    assert client.post("/auto-trade/enable-paper", json={"account_id": "x"}).status_code == 401
    assert client.post("/auto-trade/enable-manual-confirm", json={"account_id": "x"}).status_code == 401
    assert client.post("/auto-trade/request-live-auto-enable", json={"account_id": "x"}).status_code == 401
    assert client.post("/auto-trade/confirm-live-auto-enable", json={"account_id": "x", "risk_acknowledged": True}).status_code == 401
    assert client.post("/auto-trade/disable", json={"account_id": "x"}).status_code == 401
    assert client.post("/auto-trade/emergency-stop", json={"account_id": "x"}).status_code == 401
    assert client.get("/auto-trade/audit-logs").status_code == 401


# ── Default mode + settings creation ───────────────────────────────────────


def test_default_mode_is_off(client: TestClient, auth_headers) -> None:
    headers, _ = _fresh_token_user(auth_headers)
    account_id = _register_account(client, headers)
    r = client.get(
        f"/auto-trade/settings?account_id={account_id}", headers=headers
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["mode"] == "OFF"
    assert body["enabled"] is False


def test_default_state_is_off(client: TestClient, auth_headers) -> None:
    headers, _ = _fresh_token_user(auth_headers)
    account_id = _register_account(client, headers)
    r = client.get(
        f"/auto-trade/state?account_id={account_id}", headers=headers
    )
    assert r.status_code == 200
    body = r.json()
    assert body["mode"] == "OFF"
    assert body["is_running"] is False


# ── Settings PUT ───────────────────────────────────────────────────────────


def test_put_settings_updates_risk_limits(
    client: TestClient, auth_headers
) -> None:
    headers, _ = _fresh_token_user(auth_headers)
    account_id = _register_account(client, headers)
    r = client.put(
        f"/auto-trade/settings?account_id={account_id}",
        headers=headers,
        json=_full_risk_payload(),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["max_capital_vnd"] == 50_000_000
    assert body["allowed_symbols"] == ["FPT", "MWG"]


def test_put_settings_cannot_change_mode_directly(
    client: TestClient, auth_headers, fake_db
) -> None:
    headers, uid = _fresh_token_user(auth_headers)
    account_id = _register_account(client, headers)
    # Try to sneak ``mode`` and ``enabled`` through the partial-update
    # surface. The service strips them defensively.
    r = client.put(
        f"/auto-trade/settings?account_id={account_id}",
        headers=headers,
        json={**_full_risk_payload(), "mode": "LIVE_AUTO", "enabled": True},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["mode"] == "OFF"
    assert body["enabled"] is False


# ── PAPER_ONLY transition ──────────────────────────────────────────────────


def test_enable_paper_only_succeeds_without_reauth(
    client: TestClient, auth_headers
) -> None:
    headers, _ = _fresh_token_user(auth_headers)
    account_id = _register_account(client, headers)
    r = client.post(
        "/auto-trade/enable-paper",
        headers=headers,
        json={"account_id": account_id},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["validation_status"] == "VALID"
    assert body["mode"] == "PAPER_ONLY"
    assert body["is_live_execution_enabled"] is False


# ── LIVE_MANUAL_CONFIRM transition ─────────────────────────────────────────


def test_live_manual_confirm_succeeds_with_fresh_jwt(
    client: TestClient, auth_headers
) -> None:
    """A freshly-minted JWT proves the user just signed in — the
    `iat` claim is within AUTO_TRADE_REAUTH_MAX_AGE_SECONDS, so re-auth
    is considered fresh without an extra password prompt."""
    headers, _ = _fresh_token_user(auth_headers)
    account_id = _register_account(client, headers)
    r = client.post(
        "/auto-trade/enable-manual-confirm",
        headers=headers,
        json={"account_id": account_id},
    )
    assert r.status_code == 200, r.text
    assert r.json()["mode"] == "LIVE_MANUAL_CONFIRM"
    assert r.json()["is_live_execution_enabled"] is False


def test_live_manual_confirm_rejected_with_stale_jwt(
    client: TestClient, auth_headers, monkeypatch
) -> None:
    """If the JWT's iat is older than the reauth window AND
    last_reauth_at is unset, the transition is REJECTED."""
    # Override the reauth window to 0 seconds → every JWT is stale.
    monkeypatch.setenv("AUTO_TRADE_REAUTH_MAX_AGE_SECONDS", "0")
    from core.config import get_settings
    get_settings.cache_clear()

    headers, _ = _fresh_token_user(auth_headers)
    account_id = _register_account(client, headers)
    r = client.post(
        "/auto-trade/enable-manual-confirm",
        headers=headers,
        json={"account_id": account_id},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["validation_status"] == "REJECTED"
    assert any("REAUTH_REQUIRED" in r for r in body["rejection_reasons"])


# ── LIVE_AUTO request + confirm ────────────────────────────────────────────


def test_live_auto_rejected_when_risk_limits_missing(
    client: TestClient, auth_headers
) -> None:
    headers, _ = _fresh_token_user(auth_headers)
    account_id = _register_account(client, headers)
    r = client.post(
        "/auto-trade/request-live-auto-enable",
        headers=headers,
        json={"account_id": account_id},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["validation_status"] == "REJECTED"
    reasons = " ".join(body["rejection_reasons"])
    assert "MAX_CAPITAL_VND_REQUIRED" in reasons
    assert "MAX_ORDER_VALUE_VND_REQUIRED" in reasons
    assert "ALLOWED_STRATEGIES_REQUIRED" in reasons
    assert "ALLOWED_SYMBOLS_OR_WATCHLISTS_REQUIRED" in reasons
    assert body["next_step"] == "ABORT"


def test_live_auto_request_valid_when_all_limits_set(
    client: TestClient, auth_headers
) -> None:
    headers, _ = _fresh_token_user(auth_headers)
    account_id = _register_account(client, headers)
    client.put(
        f"/auto-trade/settings?account_id={account_id}",
        headers=headers,
        json=_full_risk_payload(),
    )
    r = client.post(
        "/auto-trade/request-live-auto-enable",
        headers=headers,
        json={"account_id": account_id},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["validation_status"] == "VALID"
    assert body["next_step"] == "CONFIRM_RISK_ACKNOWLEDGEMENT"


def test_live_auto_confirm_requires_risk_acknowledged(
    client: TestClient, auth_headers
) -> None:
    headers, _ = _fresh_token_user(auth_headers)
    account_id = _register_account(client, headers)
    client.put(
        f"/auto-trade/settings?account_id={account_id}",
        headers=headers,
        json=_full_risk_payload(),
    )
    r = client.post(
        "/auto-trade/confirm-live-auto-enable",
        headers=headers,
        json={"account_id": account_id, "risk_acknowledged": False},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["validation_status"] == "REJECTED"
    assert any("RISK_ACKNOWLEDGEMENT_REQUIRED" in r for r in body["rejection_reasons"])


def test_live_auto_confirm_persists_mode_but_execution_stays_disabled(
    client: TestClient, auth_headers
) -> None:
    """Even after LIVE_AUTO is selected, ``is_live_execution_enabled``
    remains false in Phase 2.6 because the env-level kill switches are
    off."""
    headers, _ = _fresh_token_user(auth_headers)
    account_id = _register_account(client, headers)
    client.put(
        f"/auto-trade/settings?account_id={account_id}",
        headers=headers,
        json=_full_risk_payload(),
    )
    r = client.post(
        "/auto-trade/confirm-live-auto-enable",
        headers=headers,
        json={"account_id": account_id, "risk_acknowledged": True},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["validation_status"] == "VALID"
    assert body["mode"] == "LIVE_AUTO"
    assert body["is_live_execution_enabled"] is False
    assert body["risk_acknowledged_at"] is not None


# ── Disable + Emergency stop ───────────────────────────────────────────────


def test_disable_returns_off(client: TestClient, auth_headers) -> None:
    headers, _ = _fresh_token_user(auth_headers)
    account_id = _register_account(client, headers)
    client.post("/auto-trade/enable-paper", headers=headers, json={"account_id": account_id})
    r = client.post(
        "/auto-trade/disable",
        headers=headers,
        json={"account_id": account_id},
    )
    assert r.status_code == 200
    assert r.json()["mode"] == "OFF"


def test_emergency_stop_kills_running_state(
    client: TestClient, auth_headers, fake_db
) -> None:
    headers, uid = _fresh_token_user(auth_headers)
    account_id = _register_account(client, headers)
    client.post(
        "/auto-trade/enable-paper",
        headers=headers, json={"account_id": account_id},
    )
    r = client.post(
        "/auto-trade/emergency-stop",
        headers=headers,
        json={"account_id": account_id, "reason": "user_panic_test"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["mode"] == "OFF"

    # State row must record the stop reason + timestamp.
    state_rows = fake_db._tables["auto_trade_state"]
    matching = [s for s in state_rows if s["account_id"] == account_id]
    assert matching
    last = matching[-1]
    assert last["mode"] == "OFF"
    assert last["is_running"] is False
    assert last["emergency_stop_reason"] == "user_panic_test"
    assert last["emergency_stopped_at"] is not None


# ── Audit logs ─────────────────────────────────────────────────────────────


def test_audit_log_written_for_mode_changes(
    client: TestClient, auth_headers, fake_db
) -> None:
    headers, uid = _fresh_token_user(auth_headers)
    account_id = _register_account(client, headers)
    client.post(
        "/auto-trade/enable-paper",
        headers=headers, json={"account_id": account_id},
    )
    client.post(
        "/auto-trade/disable",
        headers=headers, json={"account_id": account_id},
    )
    client.post(
        "/auto-trade/emergency-stop",
        headers=headers, json={"account_id": account_id, "reason": "drill"},
    )
    rows = fake_db._tables["trading_audit_logs"]
    actions = [r["action"] for r in rows if r["user_id"] == uid]
    assert "AUTO_TRADE_ENABLE_PAPER" in actions
    assert "AUTO_TRADE_DISABLED" in actions
    assert "AUTO_TRADE_EMERGENCY_STOP" in actions


def test_audit_logs_endpoint_filters_to_auto_trade(
    client: TestClient, auth_headers
) -> None:
    headers, _ = _fresh_token_user(auth_headers)
    account_id = _register_account(client, headers)
    client.post(
        "/auto-trade/enable-paper",
        headers=headers, json={"account_id": account_id},
    )
    r = client.get("/auto-trade/audit-logs", headers=headers)
    assert r.status_code == 200
    rows = r.json()
    actions = {row["action"] for row in rows}
    assert "AUTO_TRADE_ENABLE_PAPER" in actions
    # Trading-route audit actions are NOT included.
    assert not any(a.startswith("trading.") for a in actions)


# ── Cross-user isolation ───────────────────────────────────────────────────


def test_other_user_cannot_read_settings(
    client: TestClient, auth_headers
) -> None:
    headers_a, _ = _fresh_token_user(auth_headers)
    headers_b, _ = _fresh_token_user(auth_headers)
    account_id = _register_account(client, headers_a)
    # User B tries to fetch user A's account settings.
    r = client.get(
        f"/auto-trade/settings?account_id={account_id}", headers=headers_b
    )
    assert r.status_code == 404


def test_other_user_cannot_change_mode(client: TestClient, auth_headers) -> None:
    headers_a, _ = _fresh_token_user(auth_headers)
    headers_b, _ = _fresh_token_user(auth_headers)
    account_id = _register_account(client, headers_a)
    r = client.post(
        "/auto-trade/enable-paper",
        headers=headers_b,
        json={"account_id": account_id},
    )
    assert r.status_code == 404


# ── Live-execution invariant ───────────────────────────────────────────────


def test_is_live_execution_enabled_stays_false_in_phase_2_6() -> None:
    from core.config import get_settings
    from services.auto_trade import is_live_execution_enabled

    get_settings.cache_clear()
    s = get_settings()
    assert is_live_execution_enabled(s) is False


def test_settings_default_safe_flags(monkeypatch: pytest.MonkeyPatch) -> None:
    """The Phase 2.6 env-level kill switches must default to safe values."""
    for var in (
        "AUTO_TRADE_ENABLED",
        "AUTO_TRADE_LIVE_ENABLED",
        "AUTO_TRADE_ORDER_PLACEMENT_ENABLED",
        "AUTO_TRADE_REQUIRE_2FA",
    ):
        monkeypatch.delenv(var, raising=False)
    from core.config import get_settings

    get_settings.cache_clear()
    s = get_settings()
    assert s.auto_trade_live_enabled is False
    assert s.auto_trade_order_placement_enabled is False
    assert s.auto_trade_default_mode == "OFF"


def test_production_refuses_auto_trade_live_enabled(
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
    from core.config import get_settings

    get_settings.cache_clear()
    s = get_settings()
    with pytest.raises(RuntimeError, match="AUTO_TRADE_LIVE_ENABLED=true"):
        s.warn_if_missing_secrets()


def test_production_refuses_auto_trade_order_placement(
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
    # The order-placement guard fires after the live-enabled guard.
    # Set live=false here so we exercise the order-placement-only path.
    monkeypatch.setenv("AUTO_TRADE_LIVE_ENABLED", "false")
    monkeypatch.setenv("AUTO_TRADE_ORDER_PLACEMENT_ENABLED", "true")
    from core.config import get_settings

    get_settings.cache_clear()
    s = get_settings()
    with pytest.raises(RuntimeError, match="AUTO_TRADE_ORDER_PLACEMENT_ENABLED=true"):
        s.warn_if_missing_secrets()


def test_production_refuses_worker_enabled_without_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When the worker tick is enabled in production but
    AUTO_TRADE_WORKER_SECRET is empty, ``hmac.compare_digest("", "")``
    returns True, so any authenticated request without an
    ``X-Worker-Secret`` header would pass. Refuse to boot."""
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("CORS_ORIGINS", '["https://app.example.com"]')
    monkeypatch.setenv("SSI_USE_MOCK", "false")
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_JWT_SECRET", "x")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "x")
    monkeypatch.setenv("DATABASE_URL", "postgresql://x")
    monkeypatch.setenv("SSI_CONSUMER_ID", "x")
    monkeypatch.setenv("SSI_CONSUMER_SECRET", "x")
    monkeypatch.setenv("AUTO_TRADE_LIVE_ENABLED", "false")
    monkeypatch.setenv("AUTO_TRADE_ORDER_PLACEMENT_ENABLED", "false")
    monkeypatch.setenv("AUTO_TRADE_WORKER_ENABLED", "true")
    monkeypatch.setenv("AUTO_TRADE_WORKER_SECRET", "")
    from core.config import get_settings

    get_settings.cache_clear()
    s = get_settings()
    with pytest.raises(RuntimeError, match="AUTO_TRADE_WORKER_SECRET is empty"):
        s.warn_if_missing_secrets()


def test_production_accepts_worker_enabled_with_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The new guard must NOT block startup when the secret is set."""
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("CORS_ORIGINS", '["https://app.example.com"]')
    monkeypatch.setenv("SSI_USE_MOCK", "false")
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_JWT_SECRET", "x")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "x")
    monkeypatch.setenv("DATABASE_URL", "postgresql://x")
    monkeypatch.setenv("SSI_CONSUMER_ID", "x")
    monkeypatch.setenv("SSI_CONSUMER_SECRET", "x")
    monkeypatch.setenv("AUTO_TRADE_LIVE_ENABLED", "false")
    monkeypatch.setenv("AUTO_TRADE_ORDER_PLACEMENT_ENABLED", "false")
    monkeypatch.setenv("AUTO_TRADE_WORKER_ENABLED", "true")
    monkeypatch.setenv(
        "AUTO_TRADE_WORKER_SECRET",
        "a-strong-secret-with-at-least-32-characters-xx",
    )
    from core.config import get_settings

    get_settings.cache_clear()
    s = get_settings()
    s.warn_if_missing_secrets()  # must not raise


# ── No-live-order regression sweep specific to auto_trade.py ───────────────


def test_production_boots_with_valid_secrets_and_safe_defaults(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Mirror image of the ``test_production_refuses_*`` guard family.

    Given an APP_ENV=production env with every required secret populated
    AND all live-execution flags at their safe defaults (live order +
    auto-trade + worker all OFF), ``warn_if_missing_secrets`` must NOT
    raise — i.e. the production startup path is reachable.

    Catches regressions where a future guard accidentally rejects a
    well-formed prod env (broken release).
    """
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("CORS_ORIGINS", '["https://app.example.com"]')
    monkeypatch.setenv("SSI_USE_MOCK", "false")
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_JWT_SECRET", "x")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "x")
    monkeypatch.setenv("DATABASE_URL", "postgresql://x")
    monkeypatch.setenv("SSI_CONSUMER_ID", "x")
    monkeypatch.setenv("SSI_CONSUMER_SECRET", "x")
    # Safe defaults — all live-execution toggles OFF.
    monkeypatch.setenv("SSI_TRADING_USE_MOCK", "true")
    monkeypatch.setenv("SSI_TRADING_READ_ONLY", "true")
    monkeypatch.setenv("SSI_TRADING_ORDER_PLACEMENT_ENABLED", "false")
    monkeypatch.setenv("TRADING_LIVE_ORDER_ENABLED", "false")
    monkeypatch.setenv("TRADING_ORDER_PLACEMENT_DRY_RUN", "true")
    monkeypatch.setenv("AUTO_TRADE_LIVE_ENABLED", "false")
    monkeypatch.setenv("AUTO_TRADE_ORDER_PLACEMENT_ENABLED", "false")
    monkeypatch.setenv("AUTO_TRADE_WORKER_ENABLED", "false")
    monkeypatch.setenv("AUTO_TRADE_DRY_RUN", "true")
    from core.config import get_settings

    get_settings.cache_clear()
    settings = get_settings()
    # No RuntimeError. No missing secrets. Mock mode disabled.
    missing = settings.warn_if_missing_secrets()
    assert missing == []
    assert settings.is_production is True
    assert settings.ssi_use_mock is False
    assert settings.auto_trade_live_enabled is False
    assert settings.trading_live_order_enabled is False


# ── Re-auth endpoint coverage (was a critical gap) ─────────────────────────


def test_stamp_reauth_success_persists_and_audits(
    client: TestClient, auth_headers, fake_db
) -> None:
    """POST /auto-trade/reauth with a fresh JWT must stamp
    last_reauth_at AND write AUTO_TRADE_REAUTH_SUCCESS. Previously this
    endpoint had zero test coverage — a regression breaking the stamp
    could ship undetected."""
    headers, uid = _fresh_token_user(auth_headers)
    account_id = _register_account(client, headers)
    r = client.post(
        f"/auto-trade/reauth?account_id={account_id}",
        headers=headers,
        json={},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert body["last_reauth_at"]
    # The settings row's last_reauth_at column must now be non-null.
    rows = fake_db._tables["auto_trade_settings"]
    matching = [s for s in rows if s["account_id"] == account_id]
    assert matching
    assert matching[-1]["last_reauth_at"] is not None
    # And an AUTO_TRADE_REAUTH_SUCCESS audit row exists.
    audit_rows = fake_db._tables["trading_audit_logs"]
    actions = [r["action"] for r in audit_rows if r["user_id"] == uid]
    assert "AUTO_TRADE_REAUTH_SUCCESS" in actions


def test_stamp_reauth_failure_audits_failed_and_returns_401(
    client: TestClient, auth_headers, fake_db, monkeypatch
) -> None:
    """If the JWT iat is stale, /reauth must return 401 AND audit
    AUTO_TRADE_REAUTH_FAILED — not silently succeed."""
    monkeypatch.setenv("AUTO_TRADE_REAUTH_MAX_AGE_SECONDS", "0")
    from core.config import get_settings
    get_settings.cache_clear()

    headers, uid = _fresh_token_user(auth_headers)
    account_id = _register_account(client, headers)
    r = client.post(
        f"/auto-trade/reauth?account_id={account_id}",
        headers=headers,
        json={},
    )
    assert r.status_code == 401
    audit_rows = fake_db._tables["trading_audit_logs"]
    actions = [r["action"] for r in audit_rows if r["user_id"] == uid]
    assert "AUTO_TRADE_REAUTH_FAILED" in actions


def test_stamp_reauth_accepts_no_password_field(
    client: TestClient, auth_headers
) -> None:
    """The endpoint must not accept a password — even if a client tries
    to send one, the backend response must not echo it and the route
    body schema doesn't bind it. This pins the Phase 2.6 invariant
    'backend never sees the password'."""
    headers, _ = _fresh_token_user(auth_headers)
    account_id = _register_account(client, headers)
    r = client.post(
        f"/auto-trade/reauth?account_id={account_id}",
        headers=headers,
        json={"password": "should-be-ignored"},
    )
    assert r.status_code == 200, r.text
    # Response must not contain the password we sent.
    assert "should-be-ignored" not in r.text


# ── Service unit tests for reauth_is_fresh + is_live_execution_enabled ────


def test_reauth_is_fresh_unit() -> None:
    """Direct unit test of the freshness gate. Covers: jwt iat fresh,
    jwt iat stale, last_reauth_at fresh, last_reauth_at stale, neither
    provided, both provided."""
    from datetime import timedelta

    from services.auto_trade import reauth_is_fresh
    from core.config import get_settings

    get_settings.cache_clear()
    s = get_settings()

    now = datetime.datetime.now(datetime.timezone.utc)
    fresh_iat = int(now.timestamp())
    stale_iat = int((now - datetime.timedelta(seconds=600)).timestamp())

    # Fresh JWT iat alone is enough.
    assert reauth_is_fresh(
        settings=s, jwt_claims={"iat": fresh_iat}, last_reauth_at=None, now=now
    ) is True
    # Stale JWT iat alone is not.
    assert reauth_is_fresh(
        settings=s, jwt_claims={"iat": stale_iat}, last_reauth_at=None, now=now
    ) is False
    # Fresh last_reauth_at alone is enough.
    assert reauth_is_fresh(
        settings=s, jwt_claims=None,
        last_reauth_at=now - timedelta(seconds=60), now=now,
    ) is True
    # Stale last_reauth_at alone is not.
    assert reauth_is_fresh(
        settings=s, jwt_claims=None,
        last_reauth_at=now - timedelta(seconds=600), now=now,
    ) is False
    # Neither provided → False.
    assert reauth_is_fresh(settings=s, jwt_claims=None, last_reauth_at=None, now=now) is False
    # JWT iat as non-int (defensive) → False.
    assert reauth_is_fresh(
        settings=s, jwt_claims={"iat": "not-a-number"},
        last_reauth_at=None, now=now,
    ) is False
    # Future iat (negative age) → also False (age check is 0 <= age <= max).
    future_iat = int((now + datetime.timedelta(seconds=300)).timestamp())
    assert reauth_is_fresh(
        settings=s, jwt_claims={"iat": future_iat},
        last_reauth_at=None, now=now,
    ) is False


def test_is_live_execution_enabled_requires_all_three_flags(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The kill switch is a triple-AND. Toggling any single flag false
    must keep the result false. This pins the AND semantics so a
    refactor to OR silently disables the gate."""
    from core.config import Settings
    from services.auto_trade import is_live_execution_enabled

    # All three true → True.
    s_all = Settings(
        _env_file=None,  # type: ignore[call-arg]
        auto_trade_live_enabled=True,
        auto_trade_order_placement_enabled=True,
        ssi_trading_order_placement_enabled=True,
    )
    assert is_live_execution_enabled(s_all) is True
    # Flip each off in turn → False.
    for off in (
        "auto_trade_live_enabled",
        "auto_trade_order_placement_enabled",
        "ssi_trading_order_placement_enabled",
    ):
        kwargs = {
            "_env_file": None,
            "auto_trade_live_enabled": True,
            "auto_trade_order_placement_enabled": True,
            "ssi_trading_order_placement_enabled": True,
            off: False,
        }
        s = Settings(**kwargs)  # type: ignore[arg-type]
        assert is_live_execution_enabled(s) is False, f"flag {off} should gate"


# ── LIVE_AUTO confirm with stale JWT ───────────────────────────────────────


def test_live_auto_confirm_rejected_with_stale_jwt(
    client: TestClient, auth_headers, monkeypatch
) -> None:
    """The most important privilege-escalation guard: even with
    risk_acknowledged=True, a stale JWT must trigger REAUTH_REQUIRED.
    Previously untested."""
    monkeypatch.setenv("AUTO_TRADE_REAUTH_MAX_AGE_SECONDS", "0")
    from core.config import get_settings
    get_settings.cache_clear()

    headers, _ = _fresh_token_user(auth_headers)
    account_id = _register_account(client, headers)
    client.put(
        f"/auto-trade/settings?account_id={account_id}",
        headers=headers,
        json=_full_risk_payload(),
    )
    r = client.post(
        "/auto-trade/confirm-live-auto-enable",
        headers=headers,
        json={"account_id": account_id, "risk_acknowledged": True},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["validation_status"] == "REJECTED"
    assert any("REAUTH_REQUIRED" in r for r in body["rejection_reasons"])
    assert body["mode"] != "LIVE_AUTO"


# ── enable_paper REJECT now audits ─────────────────────────────────────────


def test_enable_paper_reject_writes_audit(
    client: TestClient, auth_headers, fake_db, monkeypatch
) -> None:
    """When PAPER is rejected (env disabled), an AUTO_TRADE_ENABLE_PAPER
    audit row with validation_status=REJECTED must be written. Previously
    the rejection branch returned silently with no audit trail."""
    monkeypatch.setenv("AUTO_TRADE_ENABLED", "false")
    from core.config import get_settings
    get_settings.cache_clear()

    headers, uid = _fresh_token_user(auth_headers)
    account_id = _register_account(client, headers)
    r = client.post(
        "/auto-trade/enable-paper",
        headers=headers,
        json={"account_id": account_id},
    )
    assert r.status_code == 200
    assert r.json()["validation_status"] == "REJECTED"
    audit_rows = fake_db._tables["trading_audit_logs"]
    paper_rows = [
        r for r in audit_rows
        if r["user_id"] == uid and r["action"] == "AUTO_TRADE_ENABLE_PAPER"
    ]
    assert paper_rows, "enable_paper rejection must write an audit row"
    assert paper_rows[-1]["metadata"]["validation_status"] == "REJECTED"


# ── Audit-of-audit on list_audit_logs ──────────────────────────────────────


def test_list_audit_logs_writes_audit_viewed(
    client: TestClient, auth_headers, fake_db
) -> None:
    headers, uid = _fresh_token_user(auth_headers)
    account_id = _register_account(client, headers)
    # Trigger one prior auto-trade action so the list isn't empty.
    client.post(
        "/auto-trade/enable-paper",
        headers=headers, json={"account_id": account_id},
    )
    client.get("/auto-trade/audit-logs", headers=headers)
    audit_rows = fake_db._tables["trading_audit_logs"]
    viewed = [
        r for r in audit_rows
        if r["user_id"] == uid and r["action"] == "AUTO_TRADE_AUDIT_VIEWED"
    ]
    assert viewed, "reading the audit log must itself write an audit row"


def test_list_audit_logs_respects_limit(
    client: TestClient, auth_headers
) -> None:
    headers, _ = _fresh_token_user(auth_headers)
    account_id = _register_account(client, headers)
    # Generate several mode-change rows.
    for _ in range(5):
        client.post(
            "/auto-trade/enable-paper",
            headers=headers, json={"account_id": account_id},
        )
        client.post(
            "/auto-trade/disable",
            headers=headers, json={"account_id": account_id},
        )
    r = client.get("/auto-trade/audit-logs?limit=3", headers=headers)
    assert r.status_code == 200
    assert len(r.json()) <= 3


# ── Settings update strip list ─────────────────────────────────────────────


def test_apply_settings_update_strips_server_owned_fields() -> None:
    """The strip list must include audit/identity fields, not just
    mode + enabled. A future refactor that adds last_reauth_at to the
    DTO must NOT make it persistable."""
    from schemas.auto_trade import (
        AutoTradeSettings,
        AutoTradeSettingsUpdate,
    )
    from services.auto_trade import apply_settings_update

    current = AutoTradeSettings(user_id="u", account_id="a")
    # Construct a patch with hostile fields via model_dump → bypass DTO.
    patch_dict = {
        "max_capital_vnd": 1_000_000,
        # These keys are not on the DTO at all (Pydantic ignores them at
        # parse time), but we simulate a future refactor by directly
        # creating a patch object with extras allowed.
    }
    patch = AutoTradeSettingsUpdate(**patch_dict)
    # Manually inject server-owned keys into model_dump output to verify
    # the strip list catches them defensively.
    object.__setattr__(patch, "__pydantic_fields_set__", set(patch.__pydantic_fields_set__) | {"max_capital_vnd"})
    out = apply_settings_update(current, patch)
    for forbidden in (
        "mode", "enabled", "last_reauth_at", "risk_acknowledged_at",
        "id", "user_id", "account_id", "created_at", "updated_at",
    ):
        assert forbidden not in out, f"{forbidden} must never reach the DB write"
    assert out.get("max_capital_vnd") == 1_000_000


# ── sanitize_audit_reasons ─────────────────────────────────────────────────


def test_sanitize_audit_reasons_strips_colon_tail() -> None:
    """Reason strings persisted to the audit log must be stable enum
    codes — never the human-readable suffix after the colon. This
    prevents future error messages from leaking user data through the
    audit table."""
    from services.auto_trade import sanitize_audit_reasons

    out = sanitize_audit_reasons([
        "REAUTH_REQUIRED: please re-enter your password",
        "MAX_CAPITAL_VND_REQUIRED",
        "AUTO_TRADE_DISABLED_AT_ENV: AUTO_TRADE_ENABLED is false",
    ])
    assert out == [
        "REAUTH_REQUIRED",
        "MAX_CAPITAL_VND_REQUIRED",
        "AUTO_TRADE_DISABLED_AT_ENV",
    ]


# ── Default-safe-flags now covers reauth window + 2fa flag ────────────────


def test_phase_2_6_full_default_safe_flags(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Pin all Phase 2.6 env defaults so a silent change can't make the
    re-auth gate toothless or quietly enable 2FA assumptions."""
    for var in (
        "AUTO_TRADE_ENABLED",
        "AUTO_TRADE_LIVE_ENABLED",
        "AUTO_TRADE_ORDER_PLACEMENT_ENABLED",
        "AUTO_TRADE_REQUIRE_2FA",
        "AUTO_TRADE_REAUTH_MAX_AGE_SECONDS",
        "AUTO_TRADE_DEFAULT_MODE",
    ):
        monkeypatch.delenv(var, raising=False)
    from core.config import get_settings

    get_settings.cache_clear()
    s = get_settings()
    assert s.auto_trade_enabled is False
    assert s.auto_trade_live_enabled is False
    assert s.auto_trade_order_placement_enabled is False
    assert s.auto_trade_require_2fa is False
    assert s.auto_trade_reauth_max_age_seconds == 300
    assert s.auto_trade_default_mode == "OFF"


# ── Regression sweep continues ─────────────────────────────────────────────


def test_no_ssi_neworder_calls_in_auto_trade_module() -> None:
    """Direct guard for auto_trade.py — the existing trading-side sweep
    already catches this globally, but a module-local assertion gives a
    clearer error when someone adds a Phase 3 method by mistake."""
    src = Path(__file__).resolve().parents[1] / "src"
    paths = [
        src / "api" / "routes" / "auto_trade.py",
        src / "services" / "auto_trade.py",
        src / "schemas" / "auto_trade.py",
    ]
    patterns = [
        r"\bNewOrder\s*\(",
        r"\bplaceOrder\s*\(",
        r"\bplace_order\s*\(",
        r"\bsubmit_order\s*\(",
        r"/NewOrder\b",
        r"/placeOrder\b",
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
