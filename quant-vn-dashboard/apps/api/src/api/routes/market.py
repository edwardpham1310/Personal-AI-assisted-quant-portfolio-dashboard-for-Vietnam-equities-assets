"""Market data routes — the only HTTP surface that can fan out to SSI."""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status

from core.config import Settings, get_settings
from core.deps import get_cache, get_market_provider, get_poller
from core.security import AuthContext, get_current_user
from providers.market_data.base import Interval, MarketDataProvider, ProviderError
from schemas.market import IndexInfo, OHLCVBar, ProviderStatus, Quote, Security
from services import market_cache
from services.cache import Cache
from workers.market_poller import MarketPoller


router = APIRouter()


# Validation knobs — kept in code (rather than settings) because they describe
# the public API contract and shouldn't be quietly tweaked per-deploy.
MAX_QUOTE_SYMBOLS = 50
MAX_DAILY_HISTORY_DAYS = 365
MAX_INTRADAY_DAYS = 30
ALLOWED_EXCHANGES = {"HOSE", "HNX", "UPCOM"}
ALLOWED_INTERVALS: tuple[Interval, ...] = ("1m", "5m", "15m", "30m", "1h")
SYMBOL_RE = re.compile(r"^[A-Z0-9_]{1,20}$")


def _normalize_symbol(symbol: str) -> str:
    sym = symbol.strip().upper()
    if not SYMBOL_RE.match(sym):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid symbol: {symbol!r}",
        )
    return sym


def _parse_symbol_list(raw: str) -> list[str]:
    parts = [p.strip().upper() for p in raw.split(",") if p.strip()]
    if not parts:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="At least one symbol is required.",
        )
    if len(parts) > MAX_QUOTE_SYMBOLS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Too many symbols. Max {MAX_QUOTE_SYMBOLS} per request.",
        )
    for sym in parts:
        if not SYMBOL_RE.match(sym):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid symbol: {sym!r}",
            )
    return parts


def _validate_date_range(start: date, end: date, *, max_days: int) -> None:
    today = datetime.now(timezone.utc).date()
    if start > end:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="start must be <= end.",
        )
    if end > today:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="end cannot be in the future.",
        )
    if (end - start).days > max_days:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Date range too large; max {max_days} days per request.",
        )


def _provider_error_to_http(exc: ProviderError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=str(exc))


# ─── Routes ──────────────────────────────────────────────────────────────────


@router.get("/securities", response_model=list[Security], summary="List securities")
async def list_securities(
    exchange: str | None = Query(default=None, max_length=10),
    _user: AuthContext = Depends(get_current_user),
    provider: MarketDataProvider = Depends(get_market_provider),
) -> list[Security]:
    exch = exchange.upper() if exchange else None
    if exch and exch not in ALLOWED_EXCHANGES:
        raise HTTPException(400, "Invalid exchange. Must be HOSE, HNX, or UPCOM.")
    try:
        return await provider.get_securities(exch)
    except ProviderError as exc:
        raise _provider_error_to_http(exc) from None


@router.get("/securities/{symbol}", response_model=Security, summary="Security details")
async def get_security(
    symbol: str,
    _user: AuthContext = Depends(get_current_user),
    provider: MarketDataProvider = Depends(get_market_provider),
) -> Security:
    sym = _normalize_symbol(symbol)
    try:
        return await provider.get_security_details(sym)
    except ProviderError as exc:
        raise _provider_error_to_http(exc) from None


@router.get("/indices", response_model=list[IndexInfo], summary="List VN indices")
async def list_indices(
    _user: AuthContext = Depends(get_current_user),
    provider: MarketDataProvider = Depends(get_market_provider),
) -> list[IndexInfo]:
    try:
        return await provider.get_index_list()
    except ProviderError as exc:
        raise _provider_error_to_http(exc) from None


@router.get(
    "/index-components/{index_code}",
    response_model=list[str],
    summary="Constituent symbols of an index",
)
async def get_index_components(
    index_code: str,
    _user: AuthContext = Depends(get_current_user),
    provider: MarketDataProvider = Depends(get_market_provider),
) -> list[str]:
    code = _normalize_symbol(index_code)
    try:
        return await provider.get_index_components(code)
    except ProviderError as exc:
        raise _provider_error_to_http(exc) from None


@router.get(
    "/ohlcv/daily/{symbol}",
    response_model=list[OHLCVBar],
    summary="Daily OHLCV bars for a symbol",
)
async def get_daily_ohlcv(
    symbol: str,
    start: date = Query(..., description="Inclusive start date (YYYY-MM-DD)"),
    end: date = Query(..., description="Inclusive end date (YYYY-MM-DD)"),
    _user: AuthContext = Depends(get_current_user),
    provider: MarketDataProvider = Depends(get_market_provider),
) -> list[OHLCVBar]:
    sym = _normalize_symbol(symbol)
    _validate_date_range(start, end, max_days=MAX_DAILY_HISTORY_DAYS)
    try:
        return await provider.get_daily_ohlcv(sym, start, end)
    except ProviderError as exc:
        raise _provider_error_to_http(exc) from None


@router.get(
    "/ohlcv/intraday/{symbol}",
    response_model=list[OHLCVBar],
    summary="Intraday OHLCV bars for a symbol",
)
async def get_intraday_ohlcv(
    symbol: str,
    start: date = Query(...),
    end: date = Query(...),
    interval: Interval = Query("5m"),
    _user: AuthContext = Depends(get_current_user),
    provider: MarketDataProvider = Depends(get_market_provider),
) -> list[OHLCVBar]:
    sym = _normalize_symbol(symbol)
    _validate_date_range(start, end, max_days=MAX_INTRADAY_DAYS)
    if interval not in ALLOWED_INTERVALS:
        raise HTTPException(400, f"Unsupported interval. Allowed: {ALLOWED_INTERVALS}.")
    try:
        return await provider.get_intraday_ohlcv(sym, start, end, interval)
    except ProviderError as exc:
        raise _provider_error_to_http(exc) from None


@router.get(
    "/quotes",
    response_model=list[Quote],
    summary="Latest quotes for a comma-separated list of symbols",
)
async def get_quotes(
    symbols: str = Query(..., description="Comma-separated, e.g. FPT,MWG,HPG"),
    _user: AuthContext = Depends(get_current_user),
    provider: MarketDataProvider = Depends(get_market_provider),
    settings: Settings = Depends(get_settings),
) -> list[Quote]:
    syms = _parse_symbol_list(symbols)
    try:
        quotes = await provider.get_latest_quotes(syms)
    except ProviderError as exc:
        raise _provider_error_to_http(exc) from None
    now = datetime.now(timezone.utc)
    threshold = timedelta(seconds=settings.ssi_quote_stale_seconds)
    return [
        q.model_copy(update={"stale": (now - q.ts) > threshold})
        for q in quotes
    ]


@router.get(
    "/status",
    response_model=ProviderStatus,
    summary="Market data provider readiness",
)
async def market_status(
    _user: AuthContext = Depends(get_current_user),
    provider: MarketDataProvider = Depends(get_market_provider),
) -> ProviderStatus:
    return await provider.status()


# ─── Live cache routes ──────────────────────────────────────────────────────
# These read the hot cache only. They do NOT call SSI on the request path —
# the poller is responsible for filling the cache. Use these from the
# dashboard so dozens of concurrent UI tabs don't multiply SSI load.


@router.get(
    "/live/quotes",
    response_model=list[Quote],
    summary="Latest cached quotes for a list of symbols",
)
async def live_quotes(
    symbols: str = Query(..., description="Comma-separated, e.g. FPT,MWG,HPG"),
    _user: AuthContext = Depends(get_current_user),
    cache: Cache = Depends(get_cache),
    settings: Settings = Depends(get_settings),
) -> list[Quote]:
    syms = _parse_symbol_list(symbols)
    rows = await market_cache.get_quotes(cache, syms)
    now = datetime.now(timezone.utc)
    threshold = timedelta(seconds=settings.ssi_quote_stale_seconds)
    out: list[Quote] = []
    for q in rows:
        if q is None:
            continue
        out.append(q.model_copy(update={"stale": (now - q.ts) > threshold}))
    return out


@router.get(
    "/live/indices",
    response_model=list[dict],
    summary="Latest cached index snapshots",
)
async def live_indices(
    _user: AuthContext = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
    cache: Cache = Depends(get_cache),
) -> list[dict]:
    rows = await market_cache.get_indices(cache, settings.market_core_indices)
    return [row for row in rows if row is not None]


@router.get(
    "/live/status",
    summary="Poller + cache health snapshot",
)
async def live_status(
    _user: AuthContext = Depends(get_current_user),
    cache: Cache = Depends(get_cache),
    poller: MarketPoller | None = Depends(get_poller),
    settings: Settings = Depends(get_settings),
) -> dict:
    last_poll = await market_cache.get_last_poll(cache)
    active = await poller.active_symbols() if poller else []
    return {
        "cache_backend": getattr(cache, "name", "unknown"),
        "poller_enabled": settings.enable_market_poller,
        "poller_running": poller is not None and poller.is_running,
        "active_symbols": active,
        "last_poll": last_poll,
        "quote_stale_after_seconds": settings.ssi_quote_stale_seconds,
    }
