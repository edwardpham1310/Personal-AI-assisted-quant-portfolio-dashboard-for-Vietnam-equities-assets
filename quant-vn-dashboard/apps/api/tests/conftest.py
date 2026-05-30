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
from typing import Callable

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

    # Force a re-read of Settings on the next get_settings() call, and drop
    # any cached market provider/cache that might have come from a previous test.
    from core.config import get_settings
    from core.deps import reset_cache, reset_market_provider_cache, set_poller

    get_settings.cache_clear()
    reset_market_provider_cache()
    reset_cache()
    set_poller(None)


def make_jwt(user_id: str | None = None, *, email: str = "test@example.com", expired: bool = False) -> str:
    """Sign a test JWT using the same secret the API will verify against."""
    uid = user_id or str(uuid.uuid4())
    now = datetime.datetime.now(datetime.timezone.utc)
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
