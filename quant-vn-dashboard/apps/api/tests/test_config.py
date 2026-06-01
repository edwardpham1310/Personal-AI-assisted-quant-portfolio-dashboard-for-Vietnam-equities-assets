"""Settings loader tests."""

from __future__ import annotations

import pytest

from core.config import Settings, get_settings


def test_defaults_safe_for_dev() -> None:
    settings = Settings(_env_file=None)  # type: ignore[call-arg]
    assert settings.app_env == "development"
    assert settings.api_port == 8000
    assert settings.cors_origins == ["http://localhost:3000"]
    assert settings.is_production is False


def test_cors_origins_split_from_csv() -> None:
    """The ``_split_cors`` before-validator still accepts CSV via the
    constructor path — pydantic-settings only JSON-decodes env-sourced values.
    """
    settings = Settings(
        _env_file=None,  # type: ignore[call-arg]
        cors_origins="http://a, http://b ,http://c",  # type: ignore[arg-type]
    )
    assert settings.cors_origins == ["http://a", "http://b", "http://c"]


def test_missing_secrets_reported_but_dev_does_not_raise(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("APP_ENV", "development")
    # Strip a required secret to force a "missing" report.
    monkeypatch.delenv("SUPABASE_JWT_SECRET", raising=False)
    get_settings.cache_clear()
    settings = get_settings()
    missing = settings.warn_if_missing_secrets()
    assert "supabase_jwt_secret" in missing


def test_production_refuses_to_start_with_missing_secrets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("APP_ENV", "production")
    # Use a non-localhost CORS so the production CORS guard passes and the
    # missing-secrets check is what fails.
    monkeypatch.setenv("CORS_ORIGINS", '["https://app.example.com"]')
    # Pin SSI_USE_MOCK=false so the Phase 2A guard passes; we're testing
    # the missing-secrets path specifically.
    monkeypatch.setenv("SSI_USE_MOCK", "false")
    # The conftest enables AUTO_TRADE_LIVE_ENABLED for the auto-trade
    # route tests, but the Phase 2.6 production guard refuses that flag.
    # Pin it back to false so this test exercises the missing-secrets path.
    monkeypatch.setenv("AUTO_TRADE_LIVE_ENABLED", "false")
    monkeypatch.delenv("SUPABASE_JWT_SECRET", raising=False)
    get_settings.cache_clear()
    settings = get_settings()
    with pytest.raises(RuntimeError, match="missing secrets"):
        settings.warn_if_missing_secrets()


def test_production_refuses_wildcard_cors(monkeypatch: pytest.MonkeyPatch) -> None:
    """CORS_ORIGINS=['*'] in production must fail loud."""
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("CORS_ORIGINS", '["*"]')
    monkeypatch.setenv("SSI_USE_MOCK", "false")
    get_settings.cache_clear()
    settings = get_settings()
    with pytest.raises(RuntimeError, match="CORS_ORIGINS=\\['\\*'\\]"):
        settings.warn_if_missing_secrets()


def test_production_refuses_localhost_only_cors(monkeypatch: pytest.MonkeyPatch) -> None:
    """CORS_ORIGINS left at the dev default in production must fail loud."""
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("CORS_ORIGINS", '["http://localhost:3000"]')
    monkeypatch.setenv("SSI_USE_MOCK", "false")
    get_settings.cache_clear()
    settings = get_settings()
    with pytest.raises(RuntimeError, match="only localhost CORS_ORIGINS"):
        settings.warn_if_missing_secrets()


def test_ssi_trading_keys_are_inert_in_phase_1() -> None:
    """Phase 2 placeholders may be populated, but no code path may use them
    to instantiate a Trading provider or call any order-placement endpoint.

    This regression test:
      1. Confirms the placeholder fields are parseable from env.
      2. Sweeps apps/api/src/ for any name resembling a real order call.
      3. Ensures /portfolio/sync/ssi remains the 501 placeholder.
    """
    import pathlib
    import re

    settings = Settings(
        _env_file=None,  # type: ignore[call-arg]
        ssi_trading_consumer_id="phase-2-id",
        ssi_trading_consumer_secret="phase-2-secret",
    )
    assert settings.ssi_trading_consumer_id == "phase-2-id"
    assert settings.ssi_trading_consumer_secret == "phase-2-secret"

    src_root = pathlib.Path(__file__).resolve().parents[1] / "src"
    # Require a parenthesis after the symbol so we catch CALLS, not the
    # words mentioned in docstrings or comments.
    pattern = re.compile(
        r"\b(NewOrder|placeOrder|place_order|new_order|"
        r"send_order|create_order)\s*\("
    )
    # ``submit_order`` is intentionally introduced by Phase 2.8 as the
    # provider scaffold (still gated by the 5-flag orchestrator and
    # raises 501 in this phase). It is NOT part of this allow-list test;
    # Phase 2.8 has its own ``test_no_background_submit_path_exists``
    # regression. Other patterns remain forbidden.
    offenders: list[str] = []
    for py in src_root.rglob("*.py"):
        text = py.read_text(encoding="utf-8")
        if pattern.search(text):
            offenders.append(str(py.relative_to(src_root)))
    assert offenders == [], (
        "Phase 1 must not contain any order-placement CALL. "
        f"Offenders: {offenders}"
    )


def test_production_refuses_ssi_use_mock_true(monkeypatch: pytest.MonkeyPatch) -> None:
    """Phase 2A rule: ``SSI_USE_MOCK=true`` is incompatible with
    ``APP_ENV=production``. Production must serve real SSI data.
    """
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("CORS_ORIGINS", '["https://app.example.com"]')
    monkeypatch.setenv("SSI_USE_MOCK", "true")
    # Ensure other required secrets are set so we hit the mock check, not
    # the missing-secrets check.
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_JWT_SECRET", "x")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "x")
    monkeypatch.setenv("DATABASE_URL", "postgresql://x")
    monkeypatch.setenv("SSI_CONSUMER_ID", "x")
    monkeypatch.setenv("SSI_CONSUMER_SECRET", "x")
    get_settings.cache_clear()
    settings = get_settings()
    with pytest.raises(RuntimeError, match="SSI_USE_MOCK=true"):
        settings.warn_if_missing_secrets()


def test_production_allows_ssi_use_mock_false_with_creds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Production with real SSI mode + every required secret must boot."""
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("CORS_ORIGINS", '["https://app.example.com"]')
    monkeypatch.setenv("SSI_USE_MOCK", "false")
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_JWT_SECRET", "x")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "x")
    monkeypatch.setenv("DATABASE_URL", "postgresql://x")
    monkeypatch.setenv("SSI_CONSUMER_ID", "x")
    monkeypatch.setenv("SSI_CONSUMER_SECRET", "x")
    # Conftest enables AUTO_TRADE_LIVE_ENABLED for the route tests; the
    # Phase 2.6 production guard would block startup. Pin it back to
    # false for this happy-path-prod-boot test.
    monkeypatch.setenv("AUTO_TRADE_LIVE_ENABLED", "false")
    monkeypatch.setenv("AUTO_TRADE_ORDER_PLACEMENT_ENABLED", "false")
    get_settings.cache_clear()
    settings = get_settings()
    # Should NOT raise.
    assert settings.warn_if_missing_secrets() == []


def test_production_refuses_order_placement_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Phase 2.5: production startup must refuse
    ``SSI_TRADING_ORDER_PLACEMENT_ENABLED=true``. Live order placement
    is a Phase 3 milestone gated by its own review."""
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("CORS_ORIGINS", '["https://app.example.com"]')
    monkeypatch.setenv("SSI_USE_MOCK", "false")
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_JWT_SECRET", "x")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "x")
    monkeypatch.setenv("DATABASE_URL", "postgresql://x")
    monkeypatch.setenv("SSI_CONSUMER_ID", "x")
    monkeypatch.setenv("SSI_CONSUMER_SECRET", "x")
    monkeypatch.setenv("SSI_TRADING_ORDER_PLACEMENT_ENABLED", "true")
    get_settings.cache_clear()
    settings = get_settings()
    with pytest.raises(
        RuntimeError, match="SSI_TRADING_ORDER_PLACEMENT_ENABLED=true"
    ):
        settings.warn_if_missing_secrets()


def test_phase_2_5_trading_flags_default_safe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The Phase 2.5 trading flags must default to the safe values:
    mock=true, read_only=true, order_placement_enabled=false. An operator
    can override per-env, but the *defaults* must never live-trade.
    """
    monkeypatch.delenv("SSI_TRADING_USE_MOCK", raising=False)
    monkeypatch.delenv("SSI_TRADING_READ_ONLY", raising=False)
    monkeypatch.delenv("SSI_TRADING_ORDER_PLACEMENT_ENABLED", raising=False)
    get_settings.cache_clear()
    settings = get_settings()
    assert settings.ssi_trading_use_mock is True
    assert settings.ssi_trading_read_only is True
    assert settings.ssi_trading_order_placement_enabled is False
