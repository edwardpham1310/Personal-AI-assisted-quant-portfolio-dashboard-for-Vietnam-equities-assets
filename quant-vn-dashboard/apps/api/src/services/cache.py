"""Cache abstraction.

Three implementations live here:
    * ``InMemoryCache`` — async-safe dict + TTL. Used in tests and when
      neither REDIS_URL nor Upstash REST creds are set, so dev works
      without external infra.
    * ``RedisCache`` — thin async wrapper over ``redis.asyncio``. Picked
      when ``REDIS_URL`` is set.
    * ``UpstashRestCache`` — REST adapter over Upstash's HTTPS endpoints.
      Picked when ``UPSTASH_REDIS_REST_URL`` + ``UPSTASH_REDIS_REST_TOKEN``
      are set and ``REDIS_URL`` is not. Useful for environments where
      outbound TCP to Redis is blocked but HTTPS is fine.

``build_cache(settings)`` picks the right one and falls back to in-memory
if the chosen backend fails to construct. Failures are loud in logs but
never crash the API. Errors never include URLs or credentials.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any, Protocol


logger = logging.getLogger(__name__)


class Cache(Protocol):
    async def get(self, key: str) -> str | None: ...
    async def set(self, key: str, value: str, *, ttl_seconds: float | None = None) -> None: ...
    async def delete(self, key: str) -> None: ...
    async def mget(self, keys: list[str]) -> list[str | None]: ...
    async def ping(self) -> bool: ...
    async def close(self) -> None: ...
    async def get_json(self, key: str) -> Any: ...
    async def set_json(
        self, key: str, value: Any, *, ttl_seconds: float | None = None
    ) -> None: ...


class InMemoryCache:
    """Async-safe dict with per-key TTL. Stable enough for dev + tests."""

    name = "memory"

    def __init__(self) -> None:
        self._data: dict[str, tuple[str, float | None]] = {}
        self._lock = asyncio.Lock()

    def _purge_expired(self) -> None:
        now = time.time()
        expired = [k for k, (_, exp) in self._data.items() if exp is not None and exp < now]
        for key in expired:
            self._data.pop(key, None)

    async def get(self, key: str) -> str | None:
        async with self._lock:
            self._purge_expired()
            entry = self._data.get(key)
            return entry[0] if entry else None

    async def set(self, key: str, value: str, *, ttl_seconds: float | None = None) -> None:
        async with self._lock:
            expiry = time.time() + ttl_seconds if ttl_seconds else None
            self._data[key] = (value, expiry)

    async def delete(self, key: str) -> None:
        async with self._lock:
            self._data.pop(key, None)

    async def mget(self, keys: list[str]) -> list[str | None]:
        async with self._lock:
            self._purge_expired()
            return [self._data[k][0] if k in self._data else None for k in keys]

    async def ping(self) -> bool:
        return True

    async def close(self) -> None:
        return None

    async def get_json(self, key: str) -> Any:
        raw = await self.get(key)
        return json.loads(raw) if raw else None

    async def set_json(self, key: str, value: Any, *, ttl_seconds: float | None = None) -> None:
        await self.set(key, json.dumps(value, default=str), ttl_seconds=ttl_seconds)


class RedisCache:
    """Async wrapper around ``redis.asyncio``."""

    name = "redis"

    def __init__(self, url: str) -> None:
        import redis.asyncio as redis  # imported lazily so unit tests don't need it

        self._client = redis.from_url(url, decode_responses=True)

    async def get(self, key: str) -> str | None:
        return await self._client.get(key)

    async def set(self, key: str, value: str, *, ttl_seconds: float | None = None) -> None:
        if ttl_seconds:
            await self._client.set(key, value, ex=int(max(1, ttl_seconds)))
        else:
            await self._client.set(key, value)

    async def delete(self, key: str) -> None:
        await self._client.delete(key)

    async def mget(self, keys: list[str]) -> list[str | None]:
        if not keys:
            return []
        return await self._client.mget(*keys)

    async def ping(self) -> bool:
        return bool(await self._client.ping())

    async def close(self) -> None:
        try:
            await self._client.aclose()
        except Exception as exc:
            logger.warning("redis.close_failed err=%s", type(exc).__name__)

    async def get_json(self, key: str) -> Any:
        raw = await self.get(key)
        return json.loads(raw) if raw else None

    async def set_json(self, key: str, value: Any, *, ttl_seconds: float | None = None) -> None:
        await self.set(key, json.dumps(value, default=str), ttl_seconds=ttl_seconds)


class UpstashRestCache:
    """REST adapter over Upstash's HTTPS Redis surface.

    Useful when the runtime allows outbound HTTPS but not raw TCP to Redis.
    All requests carry the bearer token; URL + token never appear in any
    log line or response.
    """

    name = "upstash_rest"

    def __init__(self, base_url: str, token: str) -> None:
        if not base_url or not token:
            raise ValueError("upstash url + token required")
        # imported lazily so unit tests that don't exercise Upstash don't
        # need httpx-on-a-real-loop fixtures.
        import httpx

        self._base = base_url.rstrip("/")
        self._headers = {"Authorization": f"Bearer {token}"}
        self._client = httpx.AsyncClient(
            headers=self._headers, timeout=httpx.Timeout(5.0)
        )

    async def _call(self, *segments: str, allow_404: bool = False) -> Any:
        # Upstash takes the command + arg path: e.g. /get/<key> or
        # /setex/<key>/<ttl>/<value>. The client URL-encodes path segments.
        url = "/".join([self._base, *segments])
        try:
            resp = await self._client.get(url)
        except Exception as exc:
            logger.warning(
                "upstash.request_failed err=%s", type(exc).__name__
            )
            return None
        if resp.status_code == 404 and allow_404:
            return None
        if resp.status_code >= 400:
            logger.warning(
                "upstash.bad_response status=%d", resp.status_code
            )
            return None
        try:
            body = resp.json()
        except Exception:
            return None
        if isinstance(body, dict) and "error" in body:
            # ``error`` strings from Upstash describe the COMMAND only —
            # never the value — so logging the literal is safe.
            logger.warning("upstash.error err=%s", body["error"][:60])
            return None
        return body.get("result") if isinstance(body, dict) else None

    async def get(self, key: str) -> str | None:
        result = await self._call("get", key, allow_404=True)
        if result is None:
            return None
        return str(result)

    async def set(
        self, key: str, value: str, *, ttl_seconds: float | None = None
    ) -> None:
        if ttl_seconds:
            await self._call("setex", key, str(int(max(1, ttl_seconds))), value)
        else:
            await self._call("set", key, value)

    async def delete(self, key: str) -> None:
        await self._call("del", key)

    async def mget(self, keys: list[str]) -> list[str | None]:
        if not keys:
            return []
        result = await self._call("mget", *keys)
        if not isinstance(result, list):
            return [None] * len(keys)
        out: list[str | None] = []
        for v in result:
            out.append(None if v is None else str(v))
        return out

    async def ping(self) -> bool:
        result = await self._call("ping")
        return result == "PONG" or result is True

    async def close(self) -> None:
        try:
            await self._client.aclose()
        except Exception as exc:
            logger.warning("upstash.close_failed err=%s", type(exc).__name__)

    async def get_json(self, key: str) -> Any:
        raw = await self.get(key)
        return json.loads(raw) if raw else None

    async def set_json(
        self, key: str, value: Any, *, ttl_seconds: float | None = None
    ) -> None:
        await self.set(key, json.dumps(value, default=str), ttl_seconds=ttl_seconds)


def build_cache(
    redis_url: str | None = None,
    *,
    upstash_url: str | None = None,
    upstash_token: str | None = None,
) -> Cache:
    """Construct a cache.

    Priority:
      1. ``redis_url`` (native protocol) — first choice when both are set.
      2. Upstash REST URL + token — used when only Upstash creds are
         present (TCP-blocked environments).
      3. In-memory fallback — used in dev/tests or when the chosen backend
         fails to construct.

    Failures are logged with ``type(exc).__name__`` only — never the URL
    or token.
    """
    if redis_url:
        try:
            cache = RedisCache(redis_url)
            logger.info("cache.using_redis")
            return cache
        except Exception as exc:
            logger.warning(
                "cache.redis_unavailable err=%s falling_back",
                type(exc).__name__,
            )
    if upstash_url and upstash_token:
        try:
            cache = UpstashRestCache(upstash_url, upstash_token)
            logger.info("cache.using_upstash_rest")
            return cache
        except Exception as exc:
            logger.warning(
                "cache.upstash_unavailable err=%s falling_back",
                type(exc).__name__,
            )
    logger.info("cache.using_in_memory (no Redis or Upstash configured)")
    return InMemoryCache()


# Back-compat shim: a small subset of older code (and tests written before
# the Upstash adapter landed) call build_cache positionally with just a URL.
# This signature continues to work because the first positional arg is
# ``redis_url``.
