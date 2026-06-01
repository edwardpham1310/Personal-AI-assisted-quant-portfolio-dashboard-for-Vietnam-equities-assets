"""Test fixtures.

Each test runs with:
    * A clean environment (no leaked dev secrets).
    * A fully populated set of Supabase test credentials (so JWT signing /
      verification works deterministically).
    * A fresh in-memory ``FakeSupabaseDB`` injected via dependency override.
    * A helper to mint JWTs signed with the test secret.
"""

from __future__ import annotations

import datetime
import os
import uuid
from collections.abc import Callable

import pytest
from fastapi.testclient import TestClient
from jose import jwt

JWT_TEST_SECRET = "test-jwt-secret-do-not-use-in-prod"
JWT_TEST_AUDIENCE = "authenticated"


@pytest.fixture(autouse=True)
def _isolate_env(monkeypatch: pytest.MonkeyPatch) -> None:
    # Strip anything the developer might have set in their shell.
    for key in list(os.environ):
        if key.startswith(("SSI_", "SUPABASE_", "REDIS_", "UPSTASH_")):
            monkeypatch.delenv(key, raising=False)

    monkeypatch.setenv("APP_ENV", "development")
    # pydantic-settings ≥ 2.6 JSON-decodes list-typed env vars at the source
    # layer before our before-validator runs. The conftest emits JSON so every
    # test file gets a settings object without per-file workarounds.
    monkeypatch.setenv("CORS_ORIGINS", '["http://localhost:3000"]')
    monkeypatch.setenv("SUPABASE_JWT_SECRET", JWT_TEST_SECRET)
    monkeypatch.setenv("SUPABASE_URL", "http://localhost:54321")
    monkeypatch.setenv("SUPABASE_ANON_KEY", "test-anon-key")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "test-service-role-key")
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql://postgres:test@localhost:54321/postgres",
    )
    monkeypatch.setenv("SSI_CONSUMER_ID", "test-consumer-id")
    monkeypatch.setenv("SSI_CONSUMER_SECRET", "test-consumer-secret")
    # All market data routes use the deterministic mock provider in tests.
    monkeypatch.setenv("SSI_USE_MOCK", "true")

    # Phase 2.5 trading defaults — mock provider, read-only, placement off.
    monkeypatch.setenv("SSI_TRADING_USE_MOCK", "true")
    monkeypatch.setenv("SSI_TRADING_READ_ONLY", "true")
    monkeypatch.setenv("SSI_TRADING_ORDER_PLACEMENT_ENABLED", "false")

    # Phase 2.9 guarded auto-trading engine defaults — all conservative.
    monkeypatch.setenv("AUTO_TRADE_DRY_RUN", "true")
    monkeypatch.setenv("AUTO_TRADE_WORKER_ENABLED", "false")
    monkeypatch.setenv("AUTO_TRADE_MAX_RUNTIME_MINUTES", "240")
    monkeypatch.setenv("AUTO_TRADE_REQUIRE_MARKET_OPEN", "false")
    monkeypatch.setenv("AUTO_TRADE_SYMBOL_COOLDOWN_MINUTES", "30")
    monkeypatch.setenv("AUTO_TRADE_WORKER_SECRET", "")
    monkeypatch.setenv("AUTO_TRADE_MAX_DECISIONS_PER_TICK", "20")

    # Phase 2.8 manual-confirm live trading — every flag conservative
    # by default so tests opting in to live submission must set them
    # explicitly. ``dry_run=true`` AND ``live_order_enabled=false`` means
    # the gate is closed → orchestrator dispatches dry-run.
    monkeypatch.setenv("TRADING_LIVE_ORDER_ENABLED", "false")
    monkeypatch.setenv("TRADING_MANUAL_CONFIRM_ENABLED", "false")
    monkeypatch.setenv("TRADING_REQUIRE_REAUTH", "true")
    monkeypatch.setenv("TRADING_REAUTH_MAX_AGE_SECONDS", "300")
    monkeypatch.setenv("TRADING_ORDER_PLACEMENT_DRY_RUN", "true")
    monkeypatch.setenv("ORDER_PREVIEW_MAX_AGE_SECONDS", "60")

    # Phase 2.6 auto-trade defaults for the test environment.
    #   * AUTO_TRADE_ENABLED=true   — mode selection routes are reachable.
    #   * AUTO_TRADE_LIVE_ENABLED=true — allows LIVE_AUTO to be SELECTED
    #     so tests can exercise the request → confirm flow. Production
    #     startup refuses this combination (verified by a separate test).
    #   * AUTO_TRADE_ORDER_PLACEMENT_ENABLED=false — execution stays off.
    #     ``is_live_execution_enabled`` returns False because of this.
    monkeypatch.setenv("AUTO_TRADE_ENABLED", "true")
    monkeypatch.setenv("AUTO_TRADE_LIVE_ENABLED", "true")
    monkeypatch.setenv("AUTO_TRADE_REAUTH_MAX_AGE_SECONDS", "300")
    monkeypatch.setenv("AUTO_TRADE_ORDER_PLACEMENT_ENABLED", "false")

    # Force a re-read of Settings on the next get_settings() call, and drop
    # any cached market provider/cache that might have come from a previous test.
    from core.config import get_settings
    from core.deps import (
        reset_cache,
        reset_market_provider_cache,
        reset_trading_provider_cache,
        set_poller,
    )

    get_settings.cache_clear()
    reset_market_provider_cache()
    reset_trading_provider_cache()
    reset_cache()
    set_poller(None)


def make_jwt(user_id: str | None = None, *, email: str = "test@example.com", expired: bool = False) -> str:
    """Sign a test JWT using the same secret the API will verify against."""
    uid = user_id or str(uuid.uuid4())
    now = datetime.datetime.now(datetime.UTC)
    iat = int(now.timestamp())
    if expired:
        exp = int((now - datetime.timedelta(hours=1)).timestamp())
    else:
        exp = int((now + datetime.timedelta(hours=1)).timestamp())
    payload = {
        "sub": uid,
        "aud": JWT_TEST_AUDIENCE,
        "iat": iat,
        "exp": exp,
        "email": email,
        "role": "authenticated",
    }
    return jwt.encode(payload, JWT_TEST_SECRET, algorithm="HS256")


@pytest.fixture()
def fake_db():
    from services.fakes import FakeSupabaseDB

    return FakeSupabaseDB()


@pytest.fixture()
def fake_cache():
    """A fresh in-memory cache, injectable via ``app.dependency_overrides``."""
    from services.cache import InMemoryCache

    return InMemoryCache()


@pytest.fixture()
def client(fake_db, fake_cache) -> TestClient:
    from core.deps import get_cache, get_db
    from main import create_app

    app = create_app()
    app.dependency_overrides[get_db] = lambda: fake_db
    app.dependency_overrides[get_cache] = lambda: fake_cache
    return TestClient(app)


# A "factory" fixture so a single test can mint several users.
@pytest.fixture()
def auth_headers() -> Callable[..., tuple[dict[str, str], str]]:
    def _make(user_id: str | None = None, email: str = "test@example.com") -> tuple[dict[str, str], str]:
        uid = user_id or str(uuid.uuid4())
        token = make_jwt(uid, email=email)
        return {"Authorization": f"Bearer {token}"}, uid

    return _make
