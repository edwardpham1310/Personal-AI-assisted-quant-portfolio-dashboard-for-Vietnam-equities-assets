"""Signal Scanner routes.

Three endpoints, all auth-required:

* ``GET /scanner/symbol/{symbol}``  — scan a single symbol.
* ``GET /scanner/watchlist/{id}``    — scan all symbols on a user's watchlist.
* ``GET /scanner/universe?vn30=true`` — scan VN30 constituents.

Per-symbol results are cached for ~60s under ``scanner:symbol:{SYM}``. The
cache key is symbol-scoped (not user-scoped) — scanner output is the same
for every user, so a hit by user A is reusable by user B.

All ``status`` labels emitted here are research signals, NOT order
recommendations.
"""

from __future__ import annotations

import asyncio
import re
from datetime import UTC, date, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, status

from core.deps import get_cache, get_db, get_market_provider
from core.security import AuthContext, get_current_user
from providers.market_data.base import MarketDataProvider, ProviderError
from schemas.scanner import ScannerResult
from services import scanner as scanner_service
from services.cache import Cache
from services.supabase_db import SupabaseDB

router = APIRouter()


# Phase 2.B: calendar days of history to pull. Bumped from 80→365 to
# guarantee ≥250 trading bars per symbol so MA200, the strict-mode
# minimum, and the 55-day breakout window all have headroom around
# Vietnamese market holidays. Preferred is 430 calendar days (≈300
# trading bars). Operators with a slower ingest path can lower this
# but the strict-mode guardrail layer then refuses BUY_CANDIDATE.
DAILY_HISTORY_DAYS = 365

# Concurrency cap for batch scans — prevents SSI rate-limit issues.
SCAN_CONCURRENCY = 5

# Per-symbol cache TTL in seconds. Short enough that intraday breakouts
# show up within the next minute.
CACHE_TTL_SECONDS = 60
CACHE_KEY = "scanner:symbol:{symbol}"

_SYMBOL_RE = re.compile(r"^[A-Z0-9_]{1,20}$")


def _normalize_symbol(symbol: str) -> str:
    sym = symbol.strip().upper()
    if not _SYMBOL_RE.match(sym):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid symbol: {symbol!r}",
        )
    return sym


def _provider_error_to_http(exc: ProviderError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=str(exc))


async def _scan_one(
    symbol: str,
    *,
    provider: MarketDataProvider,
    cache: Cache,
) -> ScannerResult | None:
    """Scan a single symbol with cache + provider error tolerance.

    Returns ``None`` when the provider rejects the symbol (e.g. unknown
    ticker) so batch endpoints can skip silently instead of failing the
    whole request.
    """
    cache_key = CACHE_KEY.format(symbol=symbol)
    cached = await cache.get_json(cache_key)
    if cached is not None:
        try:
            return ScannerResult.model_validate(cached)
        except Exception:
            # Treat a corrupt cache entry as a miss — recompute below.
            await cache.delete(cache_key)

    today = datetime.now(UTC).date()
    start: date = today - timedelta(days=DAILY_HISTORY_DAYS)
    try:
        bars = await provider.get_daily_ohlcv(symbol, start, today)
    except ProviderError:
        return None

    bars_sorted = sorted(bars, key=lambda b: b.ts)
    latest_quote = None
    try:
        quotes = await provider.get_latest_quotes([symbol])
        latest_quote = quotes[0] if quotes else None
    except ProviderError:
        latest_quote = None

    result = scanner_service.scan_symbol(symbol, bars_sorted, latest_quote=latest_quote)
    await cache.set_json(
        cache_key,
        scanner_service.result_to_dict(result),
        ttl_seconds=CACHE_TTL_SECONDS,
    )
    return result


async def _scan_many(
    symbols: list[str],
    *,
    provider: MarketDataProvider,
    cache: Cache,
) -> list[ScannerResult]:
    """Concurrent scan with a semaphore to keep SSI happy."""
    sem = asyncio.Semaphore(SCAN_CONCURRENCY)

    async def _bounded(sym: str) -> ScannerResult | None:
        async with sem:
            return await _scan_one(sym, provider=provider, cache=cache)

    results = await asyncio.gather(*[_bounded(s) for s in symbols])
    return [r for r in results if r is not None]


# ─── Routes ──────────────────────────────────────────────────────────────────


@router.get(
    "/symbol/{symbol}",
    response_model=ScannerResult,
    summary="Scan a single symbol (research signal — not a trade order)",
)
async def scan_symbol_route(
    symbol: str,
    _user: AuthContext = Depends(get_current_user),
    provider: MarketDataProvider = Depends(get_market_provider),
    cache: Cache = Depends(get_cache),
) -> ScannerResult:
    sym = _normalize_symbol(symbol)
    try:
        result = await _scan_one(sym, provider=provider, cache=cache)
    except ProviderError as exc:
        raise _provider_error_to_http(exc) from None
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Symbol not found: {sym}",
        )
    return result


@router.get(
    "/watchlist/{watchlist_id}",
    response_model=list[ScannerResult],
    summary="Scan every symbol on a user's watchlist",
)
async def scan_watchlist_route(
    watchlist_id: str,
    user: AuthContext = Depends(get_current_user),
    db: SupabaseDB = Depends(get_db),
    provider: MarketDataProvider = Depends(get_market_provider),
    cache: Cache = Depends(get_cache),
) -> list[ScannerResult]:
    parent = await db.select(
        "watchlists", where={"id": watchlist_id}, user_jwt=user.raw_token
    )
    if not parent:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Watchlist not found."
        )
    items = await db.select(
        "watchlist_items",
        where={"watchlist_id": watchlist_id},
        user_jwt=user.raw_token,
    )
    syms = sorted({str(it["symbol"]).upper() for it in items})
    if not syms:
        return []
    try:
        return await _scan_many(syms, provider=provider, cache=cache)
    except ProviderError as exc:
        raise _provider_error_to_http(exc) from None


@router.get(
    "/universe",
    response_model=list[ScannerResult],
    summary="Scan a market universe (VN30 only for now)",
)
async def scan_universe_route(
    vn30: bool = Query(default=False, description="Scan VN30 constituents."),
    _user: AuthContext = Depends(get_current_user),
    provider: MarketDataProvider = Depends(get_market_provider),
    cache: Cache = Depends(get_cache),
) -> list[ScannerResult]:
    if not vn30:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="specify vn30=true or use /scanner/watchlist",
        )
    try:
        members = await provider.get_index_components("VN30")
    except ProviderError as exc:
        raise _provider_error_to_http(exc) from None
    syms = sorted({s.upper() for s in members})
    if not syms:
        return []
    try:
        return await _scan_many(syms, provider=provider, cache=cache)
    except ProviderError as exc:
        raise _provider_error_to_http(exc) from None
