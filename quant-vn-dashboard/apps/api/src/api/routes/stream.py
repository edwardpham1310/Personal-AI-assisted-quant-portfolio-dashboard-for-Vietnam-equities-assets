"""Server-Sent Events routes.

All streams emit JSON envelopes:

    event: quote_update
    data: {"type":"quote_update","timestamp":"…","data":[…]}

Per-connection lifecycle:
    1. Client opens an SSE connection through the Next.js BFF proxy
       (which adds the Supabase JWT to the request).
    2. The handler validates inputs and subscribes the requested symbols to
       the poller so the next cycle picks them up.
    3. On each tick (``SSE_TICK_INTERVAL``), the handler reads the cache and
       emits an event only when the payload changed. A keepalive comment is
       sent every ``SSE_KEEPALIVE_INTERVAL`` seconds otherwise.
    4. On disconnect (``GeneratorExit``), the symbols are unsubscribed so
       the poller can stop pulling them when no clients care.
"""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import AsyncIterator
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse

from core.deps import get_cache, get_db, get_poller
from core.security import AuthContext, get_current_user
from services import market_cache
from services.cache import Cache
from services.supabase_db import SupabaseDB
from workers.market_poller import MarketPoller

router = APIRouter()


SSE_TICK_INTERVAL = 5.0
SSE_KEEPALIVE_INTERVAL = 15.0
SSE_MAX_SYMBOLS = 50
_SYMBOL_RE = re.compile(r"^[A-Z0-9_]{1,20}$")
_SSE_HEADERS = {
    "Cache-Control": "no-cache, no-transform",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}


def _parse_symbols(raw: str) -> list[str]:
    parts = [p.strip().upper() for p in raw.split(",") if p.strip()]
    if not parts:
        raise HTTPException(400, "At least one symbol is required.")
    if len(parts) > SSE_MAX_SYMBOLS:
        raise HTTPException(400, f"Too many symbols. Max {SSE_MAX_SYMBOLS}.")
    for sym in parts:
        if not _SYMBOL_RE.match(sym):
            raise HTTPException(400, f"Invalid symbol: {sym!r}")
    return parts


def _sse(event: str, payload: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(payload, default=str)}\n\n"


def _keepalive() -> str:
    return f": keepalive {datetime.now(UTC).isoformat()}\n\n"


async def _quote_event_loop(
    symbols: list[str],
    cache: Cache,
    poller: MarketPoller | None,
) -> AsyncIterator[str]:
    sub_token = await poller.subscribe(symbols) if poller else None
    last_payload: list[dict] | None = None
    last_emit = 0.0
    loop = asyncio.get_running_loop()
    try:
        while True:
            quotes = await market_cache.get_quotes(cache, symbols)
            payload = [q.model_dump(mode="json") for q in quotes if q is not None]
            now = loop.time()
            if payload != last_payload:
                envelope = {
                    "type": "quote_update",
                    "timestamp": datetime.now(UTC).isoformat(),
                    "data": payload,
                }
                yield _sse("quote_update", envelope)
                last_payload = payload
                last_emit = now
            elif now - last_emit > SSE_KEEPALIVE_INTERVAL:
                yield _keepalive()
                last_emit = now
            await asyncio.sleep(SSE_TICK_INTERVAL)
    except (asyncio.CancelledError, GeneratorExit):
        return
    finally:
        if sub_token and poller is not None:
            await poller.unsubscribe(sub_token)


@router.get("/heartbeat", summary="SSE liveness probe")
async def heartbeat() -> StreamingResponse:
    """Emits a ``hello`` event then a ``ping`` every 5s — no auth required."""

    async def gen() -> AsyncIterator[str]:
        yield _sse("hello", {"ts": datetime.now(UTC).isoformat()})
        try:
            while True:
                await asyncio.sleep(5)
                yield _sse("ping", {"ts": datetime.now(UTC).isoformat()})
        except (asyncio.CancelledError, GeneratorExit):
            return

    return StreamingResponse(gen(), media_type="text/event-stream", headers=_SSE_HEADERS)


@router.get("/quotes", summary="Live quote stream for a list of symbols")
async def stream_quotes(
    symbols: str = Query(..., description="Comma-separated, e.g. FPT,MWG,HPG"),
    _user: AuthContext = Depends(get_current_user),
    cache: Cache = Depends(get_cache),
    poller: MarketPoller | None = Depends(get_poller),
) -> StreamingResponse:
    syms = _parse_symbols(symbols)
    return StreamingResponse(
        _quote_event_loop(syms, cache, poller),
        media_type="text/event-stream",
        headers=_SSE_HEADERS,
    )


@router.get("/watchlist/{watchlist_id}", summary="Live quote stream for a watchlist")
async def stream_watchlist(
    watchlist_id: str,
    user: AuthContext = Depends(get_current_user),
    db: SupabaseDB = Depends(get_db),
    cache: Cache = Depends(get_cache),
    poller: MarketPoller | None = Depends(get_poller),
) -> StreamingResponse:
    # RLS would hide a watchlist that isn't ours; an empty result == 404 here.
    parent = await db.select(
        "watchlists", where={"id": watchlist_id}, user_jwt=user.raw_token
    )
    if not parent:
        raise HTTPException(404, "Watchlist not found.")
    items = await db.select(
        "watchlist_items", where={"watchlist_id": watchlist_id}, user_jwt=user.raw_token
    )
    syms = sorted({str(it["symbol"]).upper() for it in items})
    if not syms:
        # Empty watchlist — stream keepalives only so the UI shows "connected".
        async def empty() -> AsyncIterator[str]:
            yield _sse(
                "quote_update",
                {
                    "type": "quote_update",
                    "timestamp": datetime.now(UTC).isoformat(),
                    "data": [],
                },
            )
            try:
                while True:
                    await asyncio.sleep(SSE_KEEPALIVE_INTERVAL)
                    yield _keepalive()
            except (asyncio.CancelledError, GeneratorExit):
                return

        return StreamingResponse(empty(), media_type="text/event-stream", headers=_SSE_HEADERS)

    return StreamingResponse(
        _quote_event_loop(syms, cache, poller),
        media_type="text/event-stream",
        headers=_SSE_HEADERS,
    )


@router.get("/market-overview", summary="Live market overview stream")
async def stream_market_overview(
    _user: AuthContext = Depends(get_current_user),
    cache: Cache = Depends(get_cache),
) -> StreamingResponse:
    async def gen() -> AsyncIterator[str]:
        last_payload: dict | None = None
        last_emit = 0.0
        loop = asyncio.get_running_loop()
        try:
            while True:
                indices = await market_cache.get_indices(cache, ["VNINDEX", "VN30"])
                payload = {
                    "indices": [i for i in indices if i is not None],
                    "breadth": await market_cache.get_breadth(cache),
                    "top_movers": await market_cache.get_top_movers(cache),
                }
                now = loop.time()
                if payload != last_payload:
                    yield _sse(
                        "market_overview",
                        {
                            "type": "market_overview",
                            "timestamp": datetime.now(UTC).isoformat(),
                            "data": payload,
                        },
                    )
                    last_payload = payload
                    last_emit = now
                elif now - last_emit > SSE_KEEPALIVE_INTERVAL:
                    yield _keepalive()
                    last_emit = now
                await asyncio.sleep(SSE_TICK_INTERVAL)
        except (asyncio.CancelledError, GeneratorExit):
            return

    return StreamingResponse(gen(), media_type="text/event-stream", headers=_SSE_HEADERS)
