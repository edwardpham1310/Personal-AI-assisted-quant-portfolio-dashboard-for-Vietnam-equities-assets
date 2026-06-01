"""High-level read/write helpers for the market data hot cache.

All quote / index data flows through here so the cache-key schema lives in
one place. Tick data does NOT round-trip through Postgres.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from schemas.market import Quote
from services.cache import Cache

QUOTE_KEY = "quote:{symbol}"
INDEX_KEY = "index:{code}"
WATCHLIST_KEY = "watchlist:{user_id}:{watchlist_id}"
BREADTH_KEY = "market:breadth"
TOP_MOVERS_KEY = "market:top_movers"
SSI_STATUS_KEY = "system:ssi_status"
LAST_POLL_KEY = "system:last_poll"


# ── Quotes ───────────────────────────────────────────────────────────────────


async def set_quote(cache: Cache, quote: Quote, *, ttl_seconds: int) -> None:
    await cache.set_json(
        QUOTE_KEY.format(symbol=quote.symbol.upper()),
        quote.model_dump(mode="json"),
        ttl_seconds=ttl_seconds,
    )


async def get_quote(cache: Cache, symbol: str) -> Quote | None:
    payload = await cache.get_json(QUOTE_KEY.format(symbol=symbol.upper()))
    return Quote.model_validate(payload) if payload else None


async def get_quotes(cache: Cache, symbols: list[str]) -> list[Quote | None]:
    if not symbols:
        return []
    keys = [QUOTE_KEY.format(symbol=s.upper()) for s in symbols]
    raws = await cache.mget(keys)
    out: list[Quote | None] = []
    for raw in raws:
        if not raw:
            out.append(None)
            continue
        import json

        try:
            out.append(Quote.model_validate(json.loads(raw)))
        except Exception:
            out.append(None)
    return out


# ── Indices ──────────────────────────────────────────────────────────────────


async def set_index(cache: Cache, code: str, payload: dict[str, Any], *, ttl_seconds: int) -> None:
    await cache.set_json(
        INDEX_KEY.format(code=code.upper()), payload, ttl_seconds=ttl_seconds
    )


async def get_index(cache: Cache, code: str) -> dict[str, Any] | None:
    return await cache.get_json(INDEX_KEY.format(code=code.upper()))


async def get_indices(cache: Cache, codes: list[str]) -> list[dict[str, Any] | None]:
    if not codes:
        return []
    import json

    raws = await cache.mget([INDEX_KEY.format(code=c.upper()) for c in codes])
    return [json.loads(r) if r else None for r in raws]


# ── Top movers / breadth ─────────────────────────────────────────────────────


async def set_top_movers(cache: Cache, payload: Any, *, ttl_seconds: int) -> None:
    await cache.set_json(TOP_MOVERS_KEY, payload, ttl_seconds=ttl_seconds)


async def get_top_movers(cache: Cache) -> Any:
    return await cache.get_json(TOP_MOVERS_KEY)


async def set_breadth(cache: Cache, payload: Any, *, ttl_seconds: int) -> None:
    await cache.set_json(BREADTH_KEY, payload, ttl_seconds=ttl_seconds)


async def get_breadth(cache: Cache) -> Any:
    return await cache.get_json(BREADTH_KEY)


# ── Poller heartbeat / SSI status ────────────────────────────────────────────


async def set_last_poll(
    cache: Cache,
    *,
    ok: bool,
    symbol_count: int,
    error: str | None = None,
) -> None:
    await cache.set_json(
        LAST_POLL_KEY,
        {
            "ts": datetime.now(UTC).isoformat(),
            "ok": ok,
            "symbol_count": symbol_count,
            "error": error,
        },
    )


async def get_last_poll(cache: Cache) -> dict[str, Any] | None:
    return await cache.get_json(LAST_POLL_KEY)


async def set_ssi_status(cache: Cache, payload: dict[str, Any]) -> None:
    await cache.set_json(SSI_STATUS_KEY, payload)


async def get_ssi_status(cache: Cache) -> dict[str, Any] | None:
    return await cache.get_json(SSI_STATUS_KEY)
