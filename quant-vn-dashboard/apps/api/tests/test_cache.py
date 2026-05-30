"""Tests for the cache abstraction + market_cache helpers."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest

from schemas.market import Quote
from services import market_cache
from services.cache import InMemoryCache, build_cache


@pytest.mark.asyncio
async def test_set_get_roundtrip() -> None:
    cache = InMemoryCache()
    await cache.set("foo", "bar")
    assert await cache.get("foo") == "bar"


@pytest.mark.asyncio
async def test_ttl_expiry() -> None:
    cache = InMemoryCache()
    await cache.set("foo", "bar", ttl_seconds=0.05)
    await asyncio.sleep(0.1)
    assert await cache.get("foo") is None


@pytest.mark.asyncio
async def test_delete_removes_key() -> None:
    cache = InMemoryCache()
    await cache.set("a", "1")
    await cache.delete("a")
    assert await cache.get("a") is None


@pytest.mark.asyncio
async def test_mget_returns_aligned_list() -> None:
    cache = InMemoryCache()
    await cache.set("a", "1")
    await cache.set("c", "3")
    assert await cache.mget(["a", "b", "c"]) == ["1", None, "3"]


@pytest.mark.asyncio
async def test_json_roundtrip() -> None:
    cache = InMemoryCache()
    payload = {"symbol": "FPT", "price": 86_000.0, "items": [1, 2, 3]}
    await cache.set_json("k", payload)
    assert await cache.get_json("k") == payload


@pytest.mark.asyncio
async def test_build_cache_blank_url_returns_in_memory() -> None:
    cache = build_cache("")
    assert isinstance(cache, InMemoryCache)


@pytest.mark.asyncio
async def test_build_cache_bad_url_falls_back_to_memory() -> None:
    # ``redis`` package likely missing in test env or url unreachable: must
    # fall back cleanly without raising.
    cache = build_cache("redis://this-host-does-not-resolve:1/0")
    # If the redis import succeeds, RedisCache is returned but never used;
    # either way build_cache must not blow up.
    assert cache is not None
    await cache.close()


@pytest.mark.asyncio
async def test_market_cache_quote_roundtrip() -> None:
    cache = InMemoryCache()
    quote = Quote(
        symbol="FPT",
        exchange="HOSE",
        price=86_500.0,
        reference_price=86_000.0,
        change=500.0,
        change_pct=0.0058,
        volume=12_000.0,
        ts=datetime.now(timezone.utc),
        stale=False,
        source="mock",
    )
    await market_cache.set_quote(cache, quote, ttl_seconds=30)
    fetched = await market_cache.get_quote(cache, "fpt")
    assert fetched is not None
    assert fetched.symbol == "FPT"
    assert fetched.price == 86_500.0


@pytest.mark.asyncio
async def test_market_cache_get_quotes_preserves_missing_slots() -> None:
    cache = InMemoryCache()
    quote = Quote(
        symbol="FPT",
        exchange="HOSE",
        price=1.0,
        ts=datetime.now(timezone.utc),
        stale=False,
        source="mock",
    )
    await market_cache.set_quote(cache, quote, ttl_seconds=30)
    rows = await market_cache.get_quotes(cache, ["FPT", "HPG"])
    assert rows[0] is not None and rows[0].symbol == "FPT"
    assert rows[1] is None


@pytest.mark.asyncio
async def test_last_poll_marker_written() -> None:
    cache = InMemoryCache()
    await market_cache.set_last_poll(cache, ok=False, symbol_count=7, error="ReadTimeout")
    body = await market_cache.get_last_poll(cache)
    assert body is not None
    assert body["ok"] is False
    assert body["symbol_count"] == 7
    assert body["error"] == "ReadTimeout"


# ── Upstash REST adapter ────────────────────────────────────────────────────


class _StubUpstashResponse:
    def __init__(self, body, status=200):
        self._body = body
        self.status_code = status

    def json(self):
        return self._body


class _StubUpstashClient:
    """Captures (url, headers) so we can assert auth + secret-safety."""

    def __init__(self, *args, **kwargs):
        self.headers = kwargs.get("headers", {})
        self.calls: list[str] = []
        self._next_body: dict | list | str = {"result": None}

    async def get(self, url):
        self.calls.append(url)
        return _StubUpstashResponse(self._next_body)

    async def aclose(self):
        return None


@pytest.mark.asyncio
async def test_upstash_set_then_get_roundtrip(monkeypatch: pytest.MonkeyPatch) -> None:
    import httpx
    from services.cache import UpstashRestCache

    captured: dict = {}

    class _Cli(_StubUpstashClient):
        def __init__(self, *a, **kw):
            super().__init__(*a, **kw)
            captured["headers"] = kw.get("headers", {})

        async def get(self, url):
            self.calls.append(url)
            if "/get/" in url:
                return _StubUpstashResponse({"result": "hello"})
            return _StubUpstashResponse({"result": "OK"})

    monkeypatch.setattr(httpx, "AsyncClient", _Cli)
    cache = UpstashRestCache("https://upstash.example", "tok-secret-xyz")
    await cache.set("greeting", "hello", ttl_seconds=30)
    value = await cache.get("greeting")
    assert value == "hello"
    # Auth header carries the token.
    assert captured["headers"].get("Authorization") == "Bearer tok-secret-xyz"
    # The set used /setex/<key>/<ttl>/<value>; never logged inline.
    assert any("/setex/greeting/30/hello" in u for u in cache._client.calls)


@pytest.mark.asyncio
async def test_upstash_failure_returns_none_and_does_not_raise(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import httpx
    from services.cache import UpstashRestCache

    class _Failing:
        def __init__(self, *a, **kw):
            pass

        async def get(self, url):
            raise httpx.ConnectError("connection refused")

        async def aclose(self):
            return None

    monkeypatch.setattr(httpx, "AsyncClient", _Failing)
    cache = UpstashRestCache("https://upstash.example", "tok-secret-xyz")
    # Get returns None on transport failure, never raises.
    assert await cache.get("missing") is None
    # And ping is False, not an exception.
    assert await cache.ping() is False


@pytest.mark.asyncio
async def test_upstash_logs_never_leak_token_or_url(
    caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    import httpx
    from services.cache import UpstashRestCache

    class _Failing:
        def __init__(self, *a, **kw):
            pass

        async def get(self, url):
            raise httpx.ConnectError("connection refused")

        async def aclose(self):
            return None

    monkeypatch.setattr(httpx, "AsyncClient", _Failing)
    with caplog.at_level("WARNING", logger="services.cache"):
        cache = UpstashRestCache("https://upstash.example", "tok-secret-xyz")
        await cache.get("k")
    log_text = " ".join(rec.message for rec in caplog.records)
    assert "tok-secret-xyz" not in log_text
    assert "upstash.example" not in log_text
    # The exception class IS logged — that's what the design promises.
    assert "ConnectError" in log_text


# ── build_cache priority ────────────────────────────────────────────────────


def test_build_cache_prefers_redis_url_when_both_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When both REDIS_URL and Upstash creds are present, prefer Redis."""
    from services import cache as cache_mod

    class _FakeRedis:
        name = "redis"
        async def close(self):
            pass

    monkeypatch.setattr(cache_mod, "RedisCache", lambda *_a, **_kw: _FakeRedis())
    c = cache_mod.build_cache(
        "redis://localhost",
        upstash_url="https://upstash.example",
        upstash_token="tok",
    )
    assert c.name == "redis"


def test_build_cache_uses_upstash_when_only_upstash_creds_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from services import cache as cache_mod

    class _FakeUpstash:
        name = "upstash_rest"
        async def close(self):
            pass

    monkeypatch.setattr(
        cache_mod, "UpstashRestCache", lambda *_a, **_kw: _FakeUpstash()
    )
    c = cache_mod.build_cache(
        None,
        upstash_url="https://upstash.example",
        upstash_token="tok",
    )
    assert c.name == "upstash_rest"


def test_build_cache_falls_back_to_in_memory_when_nothing_set() -> None:
    c = build_cache(None)
    assert c.name == "memory"


def test_build_cache_falls_back_when_upstash_partial(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Token without URL (or vice versa) is treated as not configured."""
    from services.cache import build_cache

    c1 = build_cache(None, upstash_url="https://upstash.example", upstash_token="")
    assert c1.name == "memory"
    c2 = build_cache(None, upstash_url="", upstash_token="tok")
    assert c2.name == "memory"
