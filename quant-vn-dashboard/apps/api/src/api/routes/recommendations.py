"""Recommendation engine routes.

Three endpoints, all auth-required:

* ``GET  /recommendations/symbol/{symbol}``        — scan a single symbol.
* ``GET  /recommendations/watchlist/{watchlist_id}`` — scan a user watchlist.
* ``POST /recommendations/preview``                — what-if without DB write.

Every result carries reasons, warnings, status, and a "research signal · not
financial advice · no orders placed" disclaimer. Guardrails can downgrade an
action to ``REJECTED`` while still returning the row.
"""

from __future__ import annotations

import asyncio
import re
from datetime import UTC, date, datetime, timedelta
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import JSONResponse

from core.deps import get_cache, get_db, get_market_provider
from core.security import AuthContext, get_current_user
from providers.market_data.base import MarketDataProvider, ProviderError
from schemas.recommendation import (
    RecommendationHorizon,
    RecommendationPreviewRequest,
    RecommendationProfile,
    RecommendationResult,
)
from services import recommendation_engine as engine
from services import risk_guardrails as guards
from services.cache import Cache
from services.supabase_db import PostgrestError, SupabaseDB


router = APIRouter()


# How many calendar days of history to pull. ~80 covers MA50 + breakout +
# regime calculations with holiday padding.
DAILY_HISTORY_DAYS = 80

# How many calendar days of VNINDEX history to pull for the regime check.
VNINDEX_HISTORY_DAYS = 150

# Concurrency cap for batch scans — keeps SSI happy.
SCAN_CONCURRENCY = 5

# Per-(symbol, profile, horizon) cache TTL in seconds.
CACHE_TTL_SECONDS = 60
CACHE_KEY = "reco:{symbol}:{profile}:{horizon}"

_SYMBOL_RE = re.compile(r"^[A-Z0-9_]{1,20}$")

_DEFAULT_SHORT_HORIZON: RecommendationHorizon = "SHORT_2W"
_DEFAULT_LONG_HORIZON: RecommendationHorizon = "LONG_6M"


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


def _resolve_horizon(
    profile: RecommendationProfile, horizon: RecommendationHorizon | None
) -> RecommendationHorizon:
    if horizon is not None:
        return horizon
    return (
        _DEFAULT_SHORT_HORIZON
        if profile == "short_aggressive"
        else _DEFAULT_LONG_HORIZON
    )


# ── Data plumbing ───────────────────────────────────────────────────────────


async def _fetch_bars(
    symbol: str, *, provider: MarketDataProvider, days: int
) -> list[Any]:
    today = datetime.now(UTC).date()
    start: date = today - timedelta(days=days)
    return await provider.get_daily_ohlcv(symbol, start, today)


async def _fetch_quote(
    symbol: str, *, provider: MarketDataProvider
) -> Any | None:
    try:
        quotes = await provider.get_latest_quotes([symbol])
    except ProviderError:
        return None
    return quotes[0] if quotes else None


async def _fetch_vnindex(provider: MarketDataProvider) -> list[Any] | None:
    try:
        return await _fetch_bars(
            "VNINDEX", provider=provider, days=VNINDEX_HISTORY_DAYS
        )
    except ProviderError:
        return None
    except Exception:
        # Provider may not expose an index OHLCV endpoint in mock mode.
        return None


async def _load_portfolio_context(
    db: SupabaseDB, user_jwt: str
) -> tuple[list[dict] | None, float | None, dict | None]:
    """Return (positions-as-dicts, total_equity, cash_balance_row).

    Returns ``(None, None, None)`` cleanly when the user has no portfolio.
    """
    accounts = await db.select(
        "manual_portfolio_accounts", user_jwt=user_jwt
    )
    if not accounts:
        return None, None, None
    account_id = accounts[0]["id"]

    positions = await db.select(
        "manual_positions", where={"account_id": account_id}, user_jwt=user_jwt
    )
    cash_rows = await db.select(
        "cash_balances", where={"account_id": account_id}, user_jwt=user_jwt
    )
    cash_row = cash_rows[0] if cash_rows else None

    settled = float(cash_row.get("settled_cash", 0) or 0) if cash_row else 0.0
    pending = float(cash_row.get("pending_cash", 0) or 0) if cash_row else 0.0
    total_equity = settled + pending  # Phase 1: ignore stock_mv here; engine doesn't need it
    return positions or None, total_equity or None, cash_row


# ── Core run ────────────────────────────────────────────────────────────────


async def _run_one(
    *,
    symbol: str,
    profile: RecommendationProfile,
    horizon: RecommendationHorizon,
    provider: MarketDataProvider,
    cache: Cache,
    db: SupabaseDB | None,
    user: AuthContext | None,
    portfolio_positions: list[dict] | None,
    total_equity: float | None,
    cash_row: dict | None,
    persist: bool,
) -> RecommendationResult | None:
    cache_key = CACHE_KEY.format(symbol=symbol, profile=profile, horizon=horizon)
    cached = await cache.get_json(cache_key)
    if cached is not None:
        try:
            return RecommendationResult.model_validate(cached)
        except Exception:
            await cache.delete(cache_key)

    try:
        bars = await _fetch_bars(symbol, provider=provider, days=DAILY_HISTORY_DAYS)
    except ProviderError:
        return None
    if not bars:
        return None
    bars_sorted = sorted(bars, key=lambda b: b.ts)

    quote = await _fetch_quote(symbol, provider=provider)
    vnindex_bars = await _fetch_vnindex(provider)

    rec = engine.generate_recommendation(
        symbol=symbol,
        profile=profile,
        horizon=horizon,
        bars=bars_sorted,
        latest_quote=quote,
        vnindex_bars=vnindex_bars,
        portfolio_positions=portfolio_positions,
        total_equity=total_equity,
    )

    # Apply guardrails over a small evidence bundle.
    held_weight = None
    if portfolio_positions:
        for pos in portfolio_positions:
            if str(pos.get("symbol", "")).upper() == symbol.upper():
                # Phase 1: held weight as a fraction. Without market_value we
                # can't compute it exactly here — fall back to cost basis.
                if total_equity and total_equity > 0:
                    held_weight = float(pos.get("quantity", 0)) * float(
                        pos.get("avg_cost", 0)
                    ) / total_equity
                break

    as_of_age = None
    if quote is not None and isinstance(quote.ts, datetime):
        as_of_age = max(0.0, (datetime.now(UTC) - quote.ts).total_seconds())

    evidence = guards.GuardrailEvidence(
        # Engine now emits avg_value_20d on the result so the route does not
        # need to re-run compute_indicators just to read this number.
        avg_value_20d=rec.avg_value_20d,
        position_size_vnd=rec.position_size_vnd,
        total_equity=total_equity,
        settled_cash=float(cash_row.get("settled_cash", 0)) if cash_row else None,
        pending_cash=float(cash_row.get("pending_cash", 0)) if cash_row else None,
        has_cash_balance_row=cash_row is not None,
        quote_stale=bool(getattr(quote, "stale", False)) if quote else False,
        as_of_age_seconds=as_of_age,
        data_quality_critical=False,  # Phase 1: upstream flag not wired yet
        current_position_weight_pct=held_weight,
        last_price=rec.last_price,
    )
    final_action, final_status, final_warnings, reasons_extra = guards.apply_guardrails(
        rec, evidence
    )
    rec = rec.model_copy(
        update={
            "action": final_action,
            "status": final_status,
            "warnings": final_warnings,
            "reasons": list(rec.reasons) + reasons_extra,
        }
    )

    await cache.set_json(
        cache_key,
        rec.model_dump(mode="json"),
        ttl_seconds=CACHE_TTL_SECONDS,
    )

    if persist and db is not None and user is not None:
        await _persist_snapshot(db, user, rec)

    return rec


async def _persist_snapshot(
    db: SupabaseDB, user: AuthContext, rec: RecommendationResult
) -> None:
    """Best-effort insert into ``recommendation_snapshots``.

    Persistence failures must not break the API response — a missing snapshot
    is observable elsewhere and the user still gets the result. We narrow the
    exception to known upstream failures so genuine bugs (e.g. a missing
    column) still bubble up during development. The persist depends on the
    ``reco_insert`` RLS policy added in migration ``0004_reco_insert_policy``.
    """
    try:
        await db.insert(
            "recommendation_snapshots",
            {
                "user_id": user.user_id,
                "symbol": rec.symbol,
                "horizon": rec.horizon,
                "action": rec.action,
                "confidence": rec.confidence,
                "status": "OPEN",
                "reasons": rec.reasons,
                "warnings": rec.warnings,
                "scores": rec.scores.model_dump(),
                "profile": rec.profile,
                "entry_zone_low": rec.entry_zone_low,
                "entry_zone_high": rec.entry_zone_high,
                "stop_loss": rec.stop_loss,
                "take_profit_1": rec.take_profit_1,
                "take_profit_2": rec.take_profit_2,
                "position_size_vnd": rec.position_size_vnd,
                "estimated_quantity": rec.estimated_quantity,
                "estimated_total_cost": rec.estimated_total_cost,
                "as_of": rec.as_of,
            },
            user_jwt=user.raw_token,
        )
    except (PostgrestError, httpx.HTTPError, PermissionError) as exc:
        # Log the exception class only — never the body, which can carry
        # column/constraint detail.
        import logging
        logging.getLogger(__name__).warning(
            "reco.persist_snapshot_failed type=%s", type(exc).__name__
        )
        return


async def _run_many(
    symbols: list[str],
    *,
    profile: RecommendationProfile,
    horizon: RecommendationHorizon,
    provider: MarketDataProvider,
    cache: Cache,
    db: SupabaseDB,
    user: AuthContext,
) -> list[RecommendationResult]:
    portfolio_positions, total_equity, cash_row = await _load_portfolio_context(
        db, user.raw_token
    )
    sem = asyncio.Semaphore(SCAN_CONCURRENCY)

    async def _bounded(sym: str) -> RecommendationResult | None:
        async with sem:
            return await _run_one(
                symbol=sym,
                profile=profile,
                horizon=horizon,
                provider=provider,
                cache=cache,
                db=db,
                user=user,
                portfolio_positions=portfolio_positions,
                total_equity=total_equity,
                cash_row=cash_row,
                persist=True,
            )

    results = await asyncio.gather(*[_bounded(s) for s in symbols])
    return [r for r in results if r is not None]


# ── Routes ──────────────────────────────────────────────────────────────────


@router.get(
    "/symbol/{symbol}",
    response_model=RecommendationResult,
    summary="Recommendation for a single symbol (research signal — not a trade order)",
)
async def reco_for_symbol(
    symbol: str,
    profile: RecommendationProfile = Query(default="short_aggressive"),
    horizon: RecommendationHorizon | None = Query(default=None),
    user: AuthContext = Depends(get_current_user),
    provider: MarketDataProvider = Depends(get_market_provider),
    cache: Cache = Depends(get_cache),
    db: SupabaseDB = Depends(get_db),
) -> RecommendationResult:
    sym = _normalize_symbol(symbol)
    resolved_horizon = _resolve_horizon(profile, horizon)
    portfolio_positions, total_equity, cash_row = await _load_portfolio_context(
        db, user.raw_token
    )
    try:
        rec = await _run_one(
            symbol=sym,
            profile=profile,
            horizon=resolved_horizon,
            provider=provider,
            cache=cache,
            db=db,
            user=user,
            portfolio_positions=portfolio_positions,
            total_equity=total_equity,
            cash_row=cash_row,
            persist=True,
        )
    except ProviderError as exc:
        raise _provider_error_to_http(exc) from None
    if rec is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Symbol not found or no data: {sym}",
        )
    return rec


@router.get(
    "/watchlist/{watchlist_id}",
    response_model=list[RecommendationResult],
    summary="Recommendations for every symbol on a user's watchlist",
)
async def reco_for_watchlist(
    watchlist_id: str,
    profile: RecommendationProfile = Query(default="short_aggressive"),
    horizon: RecommendationHorizon | None = Query(default=None),
    user: AuthContext = Depends(get_current_user),
    provider: MarketDataProvider = Depends(get_market_provider),
    cache: Cache = Depends(get_cache),
    db: SupabaseDB = Depends(get_db),
) -> list[RecommendationResult]:
    resolved_horizon = _resolve_horizon(profile, horizon)
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
        return await _run_many(
            syms,
            profile=profile,
            horizon=resolved_horizon,
            provider=provider,
            cache=cache,
            db=db,
            user=user,
        )
    except ProviderError as exc:
        raise _provider_error_to_http(exc) from None


@router.post(
    "/preview",
    response_model=RecommendationResult,
    summary="What-if recommendation (no DB write)",
)
async def reco_preview(
    payload: RecommendationPreviewRequest,
    user: AuthContext = Depends(get_current_user),
    provider: MarketDataProvider = Depends(get_market_provider),
    cache: Cache = Depends(get_cache),
    db: SupabaseDB = Depends(get_db),
) -> RecommendationResult:
    sym = _normalize_symbol(payload.symbol)
    resolved_horizon = _resolve_horizon(payload.profile, payload.horizon)
    portfolio_positions, total_equity, cash_row = await _load_portfolio_context(
        db, user.raw_token
    )
    if payload.total_equity is not None:
        total_equity = payload.total_equity
    try:
        rec = await _run_one(
            symbol=sym,
            profile=payload.profile,
            horizon=resolved_horizon,
            provider=provider,
            cache=cache,
            db=None,
            user=None,
            portfolio_positions=portfolio_positions,
            total_equity=total_equity,
            cash_row=cash_row,
            persist=False,
        )
    except ProviderError as exc:
        raise _provider_error_to_http(exc) from None
    if rec is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Symbol not found or no data: {sym}",
        )
    return rec


# Legacy placeholder kept under a separate path for back-compat with any old
# clients hitting the bare ``/recommendations`` URL. New code should not use it.
@router.get("", summary="Legacy placeholder (use /symbol or /watchlist)")
def legacy_placeholder() -> JSONResponse:
    return JSONResponse(
        status_code=200,
        content={
            "status": "use_subroutes",
            "module": "recommendations",
            "message": "Use /recommendations/symbol/{sym} or /recommendations/watchlist/{id}.",
        },
    )
