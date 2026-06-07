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

from core.config import Settings, get_settings
from core.deps import get_cache, get_db, get_market_provider
from core.security import AuthContext, get_current_user
from providers.market_data.base import MarketDataProvider, ProviderError
from schemas.recommendation import (
    RecommendationExplanation,
    RecommendationHistoryItem,
    RecommendationHistoryResponse,
    RecommendationHorizon,
    RecommendationPerformanceItem,
    RecommendationPerformanceResponse,
    RecommendationPreviewRequest,
    RecommendationProfile,
    RecommendationResult,
    RecommendationScores,
    TopPick,
    TopPicksResponse,
)
from services import market_cache, portfolio_valuation
from services import recommendation_engine as engine
from services import recommendation_scoring as scoring
from services import risk_guardrails as guards
from services.cache import Cache
from services.supabase_db import PostgrestError, SupabaseDB

router = APIRouter()


def _build_unavailable_result(
    *,
    symbol: str,
    profile: RecommendationProfile,
    horizon: RecommendationHorizon,
    cause: str,
) -> RecommendationResult:
    """Phase 2 data-policy: when we cannot fetch market data for a symbol
    we still return a recommendation row so the UI can render the
    DATA_UNAVAILABLE / PROVIDER_ERROR badge. The recommendation is
    deliberately neutered — action=REJECTED, status=REJECTED — so the
    operator never sees a confident call backed by nothing.
    """
    zero_scores = RecommendationScores(
        trend=0, momentum=0, volume=0, liquidity=0, risk=50,
        risk_inverse=50, market_regime=50, portfolio_fit=100,
        ml_probability=None,
    )
    return RecommendationResult(
        symbol=symbol.upper(),
        profile=profile,
        horizon=horizon,
        action="REJECTED",
        status="REJECTED",
        confidence=0.0,
        final_score=0,
        scores=zero_scores,
        last_price=None,
        as_of=datetime.now(UTC).isoformat(),
        signals=[],
        reasons=[f"DATA_{cause}"],
        warnings=[cause.lower()],
        avg_value_20d=None,
        data_status=cause,  # type: ignore[arg-type]
        latest_quote=None,
        chart_context=None,
        chart_url=f"/market/{symbol.upper()}",
    )


# Phase 2.B: bumped from 80→365 calendar days so MA200 (≥200 bars) and
# the strict guardrail minimum (≥250 bars) have headroom around VN
# holidays. Preferred ~430 calendar days (≈300 trading bars).
DAILY_HISTORY_DAYS = 365

# Phase 2.B: VNINDEX history pulled out to 430 calendar days so the
# market-regime check can read a 200-bar trend instead of a 50-bar
# snapshot. Falls back gracefully when the upstream returns fewer.
VNINDEX_HISTORY_DAYS = 430

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


# ── History / performance helpers (Feature 5) ───────────────────────────────

# Compact range vocabulary shared with the dashboard RangeSelect dropdown.
_RANGE_DAYS: dict[str, int] = {
    "1D": 1, "1W": 7, "1M": 30, "3M": 90, "6M": 180, "1Y": 365,
}


def _range_cutoff(range_key: str, *, now: datetime | None = None) -> datetime | None:
    """Inclusive lower bound for a range key, or None for ``ALL``."""
    now = now or datetime.now(UTC)
    key = (range_key or "ALL").upper()
    if key == "ALL":
        return None
    if key == "YTD":
        return datetime(now.year, 1, 1, tzinfo=UTC)
    days = _RANGE_DAYS.get(key)
    if days is None:
        return None  # unknown key → treat as ALL (no lower bound)
    return now - timedelta(days=days)


def _parse_ts(value: Any) -> datetime | None:
    """Parse an ISO timestamp (snapshot created_at/as_of). None on failure."""
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _history_item(row: dict) -> RecommendationHistoryItem:
    """Map a stored snapshot to a history item, recomputing final_score from the
    stored component scores with the snapshot's profile weights."""
    profile = row.get("profile") or "short_aggressive"
    scores = row.get("scores") or {}
    weights = engine.PROFILE_WEIGHTS.get(profile, engine.PROFILE_WEIGHTS["short_aggressive"])
    final_score = engine.compute_final_score(scores, weights) if scores else 0
    action = str(row.get("action") or "WATCH")
    return RecommendationHistoryItem(
        id=row.get("id"),
        symbol=str(row.get("symbol", "")).upper(),
        profile=profile,
        horizon=str(row.get("horizon") or ""),
        action=action,
        signal=scoring.signal_from(action, final_score),  # type: ignore[arg-type]
        strength=scoring.strength_from_score(final_score),  # type: ignore[arg-type]
        final_score=final_score,
        confidence=_to_float(row.get("confidence")),
        status=str(row.get("status") or "OPEN"),
        reference_price=_to_float(row.get("reference_price")),
        reasons=list(row.get("reasons") or []),
        warnings=list(row.get("warnings") or []),
        created_at=row.get("created_at"),
        as_of=row.get("as_of"),
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
    db: SupabaseDB, user_jwt: str, *, cache: Cache | None = None
) -> tuple[list[Any] | None, float | None, dict | None]:
    """Return (positions, total_equity, cash_balance_row).

    Returns ``(None, None, None)`` cleanly when the user has no portfolio.

    Feature 7: when ``cache`` is supplied, positions are enriched with a
    ``weight`` (market value within holdings) via the portfolio-valuation
    service, so the engine can surface accurate held-weight / concentration
    facts. Without a cache (or with cold quotes) we fall back to the raw rows —
    the engine still detects "held" by symbol, just without a precise weight.
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

    enriched: list[Any] | None = positions or None
    if positions and cache is not None:
        syms = [str(p.get("symbol", "")).upper() for p in positions]
        quotes = await market_cache.get_quotes(cache, syms)
        _, enriched_positions = portfolio_valuation.compute_summary(positions, quotes)
        enriched = enriched_positions or positions

    return enriched, total_equity or None, cash_row


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

    # Phase 2 data policy: track provider failures so the recommendation
    # carries data_status=PROVIDER_ERROR / DATA_UNAVAILABLE rather than
    # being silently dropped.
    bars_provider_error = False
    try:
        bars = await _fetch_bars(symbol, provider=provider, days=DAILY_HISTORY_DAYS)
    except ProviderError:
        bars = []
        bars_provider_error = True
    if not bars:
        # Empty bars = symbol unknown OR provider returned nothing.
        # We still return a result with data_status set, so the UI can
        # render the "data unavailable" badge. Action defaults to WATCH.
        return _build_unavailable_result(
            symbol=symbol,
            profile=profile,
            horizon=horizon,
            cause="PROVIDER_ERROR" if bars_provider_error else "DATA_UNAVAILABLE",
        )
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

    # Apply guardrails over a small evidence bundle. Positions may be raw dicts
    # or enriched (Feature 7) EnrichedPosition models — read both via getattr/get.
    held_weight = None
    if portfolio_positions:
        for pos in portfolio_positions:
            sym = pos.get("symbol") if isinstance(pos, dict) else getattr(pos, "symbol", None)
            if str(sym or "").upper() != symbol.upper():
                continue
            # Phase 1: held weight as a fraction of equity. Without market_value
            # we fall back to cost basis (quantity * avg_cost / total_equity).
            if total_equity and total_equity > 0:
                qty = pos.get("quantity") if isinstance(pos, dict) else getattr(pos, "quantity", 0)
                avg = pos.get("avg_cost") if isinstance(pos, dict) else getattr(pos, "avg_cost", 0)
                held_weight = float(qty or 0) * float(avg or 0) / total_equity
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
    # Phase 2 chart context: set the chart_url for the UI deep-link.
    rec = rec.model_copy(update={"chart_url": f"/market/{rec.symbol}"})

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
                # Feature 5: capture the mark price now so /performance can
                # compute an honest hypothetical return later. May be None.
                "reference_price": rec.last_price,
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
        db, user.raw_token, cache=cache
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
        db, user.raw_token, cache=cache
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
    "/explain/{symbol}",
    response_model=RecommendationExplanation,
    summary="Explain one symbol's score (weighted breakdown — research signal, not advice)",
)
async def reco_explain(
    symbol: str,
    profile: RecommendationProfile = Query(default="short_aggressive"),
    horizon: RecommendationHorizon | None = Query(default=None),
    user: AuthContext = Depends(get_current_user),
    provider: MarketDataProvider = Depends(get_market_provider),
    cache: Cache = Depends(get_cache),
    db: SupabaseDB = Depends(get_db),
) -> RecommendationExplanation:
    """Derived 'why' view for a single symbol: per-component weighted
    contributions, the action threshold used, and a plain-language summary.
    Read-only — does NOT persist a snapshot (the /symbol endpoint owns that)."""
    sym = _normalize_symbol(symbol)
    resolved_horizon = _resolve_horizon(profile, horizon)
    portfolio_positions, total_equity, cash_row = await _load_portfolio_context(
        db, user.raw_token, cache=cache
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
            persist=False,
        )
    except ProviderError as exc:
        raise _provider_error_to_http(exc) from None
    if rec is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Symbol not found or no data: {sym}",
        )
    return scoring.build_explanation(rec)


@router.get(
    "/history",
    response_model=RecommendationHistoryResponse,
    summary="Past recommendation snapshots for the current user (time-series, ascending)",
)
async def reco_history(
    range_: str = Query(default="ALL", alias="range"),
    symbol: str | None = Query(default=None),
    limit: int = Query(default=200, ge=1, le=1000),
    user: AuthContext = Depends(get_current_user),
    db: SupabaseDB = Depends(get_db),
) -> RecommendationHistoryResponse:
    """RLS-scoped snapshot history. Filtered by an optional compact range
    (1D/1W/1M/3M/6M/YTD/1Y/ALL) and optional symbol, sorted ascending by
    timestamp (time-series rule). Honest-empty when there are no snapshots."""
    rows = await db.select("recommendation_snapshots", user_jwt=user.raw_token)
    cutoff = _range_cutoff(range_)
    want_symbol = symbol.strip().upper() if symbol else None

    items: list[RecommendationHistoryItem] = []
    for row in rows:
        if want_symbol and str(row.get("symbol", "")).upper() != want_symbol:
            continue
        ts = _parse_ts(row.get("created_at") or row.get("as_of"))
        if cutoff is not None and (ts is None or ts < cutoff):
            continue
        items.append(_history_item(row))

    items.sort(key=lambda it: it.created_at or it.as_of or "")
    if len(items) > limit:
        items = items[-limit:]  # keep the most recent, still ascending
    return RecommendationHistoryResponse(
        items=items,
        count=len(items),
        range=range_.upper() if range_ else "ALL",
        as_of=datetime.now(UTC).isoformat(),
    )


@router.get(
    "/performance",
    response_model=RecommendationPerformanceResponse,
    summary="Hypothetical mark-to-market of past signals (not executed trades)",
)
async def reco_performance(
    range_: str = Query(default="ALL", alias="range"),
    symbol: str | None = Query(default=None),
    user: AuthContext = Depends(get_current_user),
    cache: Cache = Depends(get_cache),
    db: SupabaseDB = Depends(get_db),
) -> RecommendationPerformanceResponse:
    """For snapshots in range that captured a ``reference_price``, compute the
    hypothetical return to the latest cached quote. Clearly NOT an executed
    trade — research review only. Honest-empty when no prices are available."""
    now_iso = datetime.now(UTC).isoformat()
    rows = await db.select("recommendation_snapshots", user_jwt=user.raw_token)
    cutoff = _range_cutoff(range_)
    want_symbol = symbol.strip().upper() if symbol else None

    in_range: list[dict] = []
    for row in rows:
        if want_symbol and str(row.get("symbol", "")).upper() != want_symbol:
            continue
        ts = _parse_ts(row.get("created_at") or row.get("as_of"))
        if cutoff is not None and (ts is None or ts < cutoff):
            continue
        in_range.append(row)

    symbols = sorted({str(r.get("symbol", "")).upper() for r in in_range if r.get("symbol")})
    quotes = await market_cache.get_quotes(cache, symbols) if symbols else []
    qmap = {q.symbol.upper(): q for q in quotes if q is not None}

    items: list[RecommendationPerformanceItem] = []
    skipped_no_reference = 0
    skipped_no_quote = 0
    for row in in_range:
        ref = _to_float(row.get("reference_price"))
        if ref is None or ref <= 0:
            skipped_no_reference += 1
            continue
        q = qmap.get(str(row.get("symbol", "")).upper())
        price = _to_float(getattr(q, "price", None)) if q else None
        if price is None:
            skipped_no_quote += 1
            continue
        action = str(row.get("action") or "WATCH")
        final_score = 0
        scores = row.get("scores") or {}
        if scores:
            profile = row.get("profile") or "short_aggressive"
            final_score = engine.compute_final_score(
                scores,
                engine.PROFILE_WEIGHTS.get(profile, engine.PROFILE_WEIGHTS["short_aggressive"]),
            )
        items.append(
            RecommendationPerformanceItem(
                id=row.get("id"),
                symbol=str(row.get("symbol", "")).upper(),
                horizon=str(row.get("horizon") or ""),
                action=action,
                signal=scoring.signal_from(action, final_score),  # type: ignore[arg-type]
                reference_price=ref,
                current_price=price,
                return_pct=(price - ref) / ref,
                stale=bool(getattr(q, "stale", False)),
                created_at=row.get("created_at"),
                priced_as_of=(q.ts.isoformat() if q and isinstance(q.ts, datetime) else now_iso),
            )
        )

    items.sort(key=lambda it: it.created_at or "")
    evaluated = len(items)
    win_rate = (
        sum(1 for it in items if it.return_pct > 0) / evaluated if evaluated else None
    )
    avg_return = sum(it.return_pct for it in items) / evaluated if evaluated else None
    best = max(items, key=lambda it: it.return_pct) if items else None
    worst = min(items, key=lambda it: it.return_pct) if items else None
    return RecommendationPerformanceResponse(
        items=items,
        total=len(in_range),
        evaluated=evaluated,
        skipped_no_reference=skipped_no_reference,
        skipped_no_quote=skipped_no_quote,
        win_rate=win_rate,
        avg_return_pct=avg_return,
        best=best,
        worst=worst,
        range=range_.upper() if range_ else "ALL",
        as_of=now_iso,
    )


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
        db, user.raw_token, cache=cache
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
async def _load_security_names(
    db: SupabaseDB, user: AuthContext, symbols: list[str]
) -> dict[str, str]:
    """Best-effort company names from the securities master. Returns {} if the
    table isn't readable (e.g. fakes / RLS) — names are optional."""
    try:
        rows = await db.select("securities", user_jwt=user.raw_token)
    except Exception:  # noqa: BLE001 - names are best-effort, never fatal
        return {}
    wanted = {s.upper() for s in symbols}
    return {
        str(r["symbol"]).upper(): r["name"]
        for r in rows
        if r.get("symbol") and r.get("name") and str(r["symbol"]).upper() in wanted
    }


async def _build_top_picks(
    symbols: list[str],
    *,
    profile: RecommendationProfile,
    coverage: str,
    exchange: str | None,
    limit: int,
    provider: MarketDataProvider,
    cache: Cache,
    db: SupabaseDB,
    user: AuthContext,
) -> TopPicksResponse:
    """Score a symbol set with the SAME engine used for watchlist recs, map to
    strength/signal, and rank. Shared by /top and /watchlist/{id}/picks so the
    two surfaces never diverge. Honest-empty on no data; no order path."""
    now_iso = datetime.now(UTC).isoformat()
    symbols = [s.upper() for s in symbols]
    if not symbols:
        return TopPicksResponse(picks=[], coverage=coverage, universe_size=0, as_of=now_iso)

    horizon = _resolve_horizon(profile, None)
    results = await _run_many(
        symbols, profile=profile, horizon=horizon,
        provider=provider, cache=cache, db=db, user=user,
    )
    quotes = await market_cache.get_quotes(cache, symbols)
    qmap = {q.symbol.upper(): q for q in quotes if q is not None}
    names = await _load_security_names(db, user, symbols)

    picks: list[TopPick] = []
    for r in results:
        q = qmap.get(r.symbol)
        ex = q.exchange if q else None
        if exchange and (ex or "").upper() != exchange.upper():
            continue
        picks.append(
            TopPick(
                symbol=r.symbol,
                company_name=names.get(r.symbol),
                exchange=ex,
                sector=None,
                price=(q.price if q else r.last_price),
                change_pct=(q.change_pct if q else None),
                volume=(q.volume if q else None),
                value=(q.value if q else None),
                quant_score=r.final_score,
                strength=scoring.strength_from_score(r.final_score),
                signal=scoring.signal_from(r.action, r.final_score),
                confidence=r.confidence,
                reasons=list(r.reasons),
                risks=list(r.warnings) + list(r.rejection_reasons),
                last_updated=(q.ts.isoformat() if q else now_iso),
            )
        )
    picks.sort(key=lambda p: p.quant_score, reverse=True)
    return TopPicksResponse(
        picks=picks[: max(1, limit)],
        coverage=coverage,
        universe_size=len(symbols),
        as_of=now_iso,
    )


@router.get(
    "/top",
    response_model=TopPicksResponse,
    summary="Top quant picks over the tracked universe (research signals — not advice)",
)
async def reco_top(
    limit: int = Query(default=10, ge=1, le=50),
    strategy: RecommendationProfile = Query(default="short_aggressive"),
    range_: str | None = Query(default=None, alias="range"),  # reserved: point-in-time
    sector: str | None = Query(default=None),  # no source yet (see TopPick.sector)
    exchange: str | None = Query(default=None),
    user: AuthContext = Depends(get_current_user),
    provider: MarketDataProvider = Depends(get_market_provider),
    cache: Cache = Depends(get_cache),
    db: SupabaseDB = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> TopPicksResponse:
    """Rank the tracked-universe symbols by the engine score, mapped to
    strength/signal. ``sector``/``range`` are accepted for API stability but not
    applied (no sector source; picks are point-in-time)."""
    try:
        return await _build_top_picks(
            [s.upper() for s in settings.market_core_symbols],
            profile=strategy, coverage="tracked_universe", exchange=exchange,
            limit=limit, provider=provider, cache=cache, db=db, user=user,
        )
    except ProviderError as exc:
        raise _provider_error_to_http(exc) from None


@router.get(
    "/watchlist/{watchlist_id}/picks",
    response_model=TopPicksResponse,
    summary="Ranked picks for a watchlist (same scoring as Top Picks)",
)
async def reco_watchlist_picks(
    watchlist_id: str,
    limit: int = Query(default=50, ge=1, le=100),
    strategy: RecommendationProfile = Query(default="short_aggressive"),
    exchange: str | None = Query(default=None),
    user: AuthContext = Depends(get_current_user),
    provider: MarketDataProvider = Depends(get_market_provider),
    cache: Cache = Depends(get_cache),
    db: SupabaseDB = Depends(get_db),
) -> TopPicksResponse:
    """Top-picks scoring (strength/signal) over a user's watchlist symbols.
    Auth + ownership gated; honest-empty for an empty watchlist."""
    parent = await db.select(
        "watchlists", where={"id": watchlist_id}, user_jwt=user.raw_token
    )
    if not parent:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Watchlist not found."
        )
    items = await db.select(
        "watchlist_items", where={"watchlist_id": watchlist_id}, user_jwt=user.raw_token
    )
    syms = sorted({str(it["symbol"]).upper() for it in items})
    try:
        return await _build_top_picks(
            syms, profile=strategy, coverage="watchlist", exchange=exchange,
            limit=limit, provider=provider, cache=cache, db=db, user=user,
        )
    except ProviderError as exc:
        raise _provider_error_to_http(exc) from None


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
