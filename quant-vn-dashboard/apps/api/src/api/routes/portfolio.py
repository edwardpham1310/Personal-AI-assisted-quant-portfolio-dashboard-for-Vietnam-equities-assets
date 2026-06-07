"""Manual portfolio routes.

MVP scope: users record their own accounts + positions. No live broker sync
yet, and absolutely no order placement.

Two route families live here:
* ``/portfolio/manual/*`` — the original CRUD surface (preserved as-is).
* ``/portfolio/{summary,positions,sync/ssi}`` — the Phase 1 valuation surface
  that uses the user's *default* account implicitly.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status

from core.config import Settings, get_settings
from core.deps import get_cache, get_db, get_trading_provider
from core.security import AuthContext, get_current_user
from providers.trading.base import TradingProvider, TradingProviderError
from schemas.portfolio import (
    AllocationResponse,
    AllocationSlice,
    EnrichedPosition,
    EquityPoint,
    EquitySnapshotRunResult,
    ManualAccount,
    ManualAccountCreate,
    ManualAccountWithPositions,
    ManualPortfolioSnapshot,
    ManualPosition,
    ManualPositionCreate,
    ManualPositionUpdate,
    PortfolioSummary,
    PositionCreate,
    PositionDayPnl,
    PositionUpdate,
    RiskScoreResult,
    TodayPnlResponse,
)
from schemas.trading import SsiAccountSnapshot
from services import (
    market_cache,
    portfolio_risk,
    portfolio_snapshots,
    portfolio_valuation,
)
from services.cache import Cache
from services.portfolio_risk import RiskParams
from services.supabase_db import SupabaseDB

router = APIRouter()


DEFAULT_ACCOUNT_NAME = "Default"


async def _list_user_accounts(
    db: SupabaseDB, user: AuthContext
) -> list[dict[str, Any]]:
    return await db.select(
        "manual_portfolio_accounts",
        where={"user_id": user.user_id},
        user_jwt=user.raw_token,
    )


async def _get_default_account(
    db: SupabaseDB,
    user: AuthContext,
    *,
    create_if_missing: bool = False,
) -> dict[str, Any] | None:
    """Return the user's default (oldest) account, optionally auto-creating."""
    accounts = await _list_user_accounts(db, user)
    if accounts:
        # ``created_at`` may be missing in old fakes — fall back to id ordering.
        return sorted(accounts, key=lambda a: a.get("created_at") or a.get("id", ""))[0]
    if not create_if_missing:
        return None
    row = await db.insert(
        "manual_portfolio_accounts",
        {
            "user_id": user.user_id,
            "name": DEFAULT_ACCOUNT_NAME,
            "broker": "SSI",
            "currency": "VND",
        },
        user_jwt=user.raw_token,
    )
    return row


@router.get(
    "/manual",
    response_model=ManualPortfolioSnapshot,
    summary="List the current user's manual portfolio (accounts + positions)",
)
async def list_manual_portfolio(
    user: AuthContext = Depends(get_current_user),
    db: SupabaseDB = Depends(get_db),
) -> ManualPortfolioSnapshot:
    accounts = await db.select(
        "manual_portfolio_accounts",
        where={"user_id": user.user_id},
        user_jwt=user.raw_token,
    )
    if not accounts:
        return ManualPortfolioSnapshot(accounts=[])
    # Defense-in-depth: scope positions to the user's own account ids explicitly
    # (in addition to RLS) so a misconfigured policy can't leak another user's
    # rows. PostgREST/FakeSupabaseDB ``select`` supports equality filters only,
    # so fetch per account — a personal portfolio has 1–3 accounts.
    by_account: dict[str, list[ManualPosition]] = {}
    for acc in accounts:
        rows = await db.select(
            "manual_positions",
            where={"account_id": acc["id"]},
            user_jwt=user.raw_token,
        )
        by_account[acc["id"]] = [ManualPosition.model_validate(row) for row in rows]
    return ManualPortfolioSnapshot(
        accounts=[
            ManualAccountWithPositions(**acc, positions=by_account.get(acc["id"], []))
            for acc in accounts
        ]
    )


@router.post(
    "/manual/accounts",
    response_model=ManualAccount,
    status_code=status.HTTP_201_CREATED,
    summary="Create a manual portfolio account",
)
async def create_account(
    payload: ManualAccountCreate,
    user: AuthContext = Depends(get_current_user),
    db: SupabaseDB = Depends(get_db),
) -> ManualAccount:
    row = await db.insert(
        "manual_portfolio_accounts",
        {
            "user_id": user.user_id,
            "name": payload.name,
            "broker": payload.broker,
            "currency": payload.currency,
        },
        user_jwt=user.raw_token,
    )
    return ManualAccount.model_validate(row)


@router.post(
    "/manual/positions",
    response_model=ManualPosition,
    status_code=status.HTTP_201_CREATED,
    summary="Record a manual position in an account you own",
)
async def create_position(
    payload: ManualPositionCreate,
    user: AuthContext = Depends(get_current_user),
    db: SupabaseDB = Depends(get_db),
) -> ManualPosition:
    parent = await db.select(
        "manual_portfolio_accounts",
        where={"id": payload.account_id},
        user_jwt=user.raw_token,
    )
    if not parent:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Account not found."
        )
    try:
        row = await db.insert(
            "manual_positions",
            {
                "account_id": payload.account_id,
                "symbol": payload.symbol.upper(),
                "exchange": payload.exchange,
                "quantity": payload.quantity,
                "avg_cost": payload.avg_cost,
                "strategy_tag": payload.strategy_tag,
                "note": payload.note,
            },
            user_jwt=user.raw_token,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    return ManualPosition.model_validate(row)


@router.put(
    "/manual/positions/{position_id}",
    response_model=ManualPosition,
    summary="Update a manual position",
)
async def update_position(
    position_id: str,
    payload: ManualPositionUpdate,
    user: AuthContext = Depends(get_current_user),
    db: SupabaseDB = Depends(get_db),
) -> ManualPosition:
    patch = payload.model_dump(exclude_none=True)
    if "symbol" in patch:
        patch["symbol"] = patch["symbol"].upper()
    if not patch:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Empty update payload."
        )
    rows = await db.update(
        "manual_positions",
        patch,
        where={"id": position_id},
        user_jwt=user.raw_token,
    )
    if not rows:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Position not found."
        )
    return ManualPosition.model_validate(rows[0])


@router.delete(
    "/manual/positions/{position_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a manual position",
)
async def delete_position(
    position_id: str,
    user: AuthContext = Depends(get_current_user),
    db: SupabaseDB = Depends(get_db),
) -> None:
    deleted = await db.delete(
        "manual_positions",
        where={"id": position_id},
        user_jwt=user.raw_token,
    )
    if deleted == 0:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Position not found."
        )


# ─── Phase 1 valuation surface ────────────────────────────────────────────────


async def _load_positions_for_user(
    db: SupabaseDB,
    user: AuthContext,
    account_id: str,
) -> list[dict[str, Any]]:
    return await db.select(
        "manual_positions",
        where={"account_id": account_id},
        user_jwt=user.raw_token,
    )


@router.get(
    "/summary",
    response_model=PortfolioSummary,
    summary="Portfolio valuation summary (research only — not financial advice)",
)
async def get_portfolio_summary(
    user: AuthContext = Depends(get_current_user),
    db: SupabaseDB = Depends(get_db),
    cache: Cache = Depends(get_cache),
) -> PortfolioSummary:
    account = await _get_default_account(db, user)
    if account is None:
        return PortfolioSummary()
    positions = await _load_positions_for_user(db, user, account["id"])
    if not positions:
        return PortfolioSummary()
    symbols = [str(p["symbol"]).upper() for p in positions]
    quotes = await market_cache.get_quotes(cache, symbols)
    summary, _ = portfolio_valuation.compute_summary(positions, quotes)
    return summary


@router.get(
    "/today-pnl",
    response_model=TodayPnlResponse,
    summary="Intraday mark-to-market PnL vs session reference (research only)",
)
async def get_today_pnl(
    user: AuthContext = Depends(get_current_user),
    db: SupabaseDB = Depends(get_db),
    cache: Cache = Depends(get_cache),
) -> TodayPnlResponse:
    account = await _get_default_account(db, user)
    if account is None:
        return TodayPnlResponse()
    positions = await _load_positions_for_user(db, user, account["id"])
    if not positions:
        return TodayPnlResponse()

    symbols = [str(p["symbol"]).upper() for p in positions]
    quotes = await market_cache.get_quotes(cache, symbols)
    rows: list[PositionDayPnl] = []
    total = 0.0
    warnings: list[str] = []
    latest_ts: str | None = None

    for pos, quote in zip(positions, quotes, strict=False):
        sym = str(pos["symbol"]).upper()
        qty = int(pos.get("quantity") or 0)
        if quote is None:
            warnings.append(f"quote_missing:{sym}")
            rows.append(PositionDayPnl(symbol=sym, quantity=qty))
            continue
        prev = quote.reference_price
        price = quote.price
        day_pnl: float | None = None
        day_pct: float | None = None
        if prev is not None:
            day_pnl = (price - prev) * qty
            total += day_pnl
            base = prev * qty
            day_pct = (day_pnl / base) if base else None
        else:
            warnings.append(f"reference_price_missing:{sym}")
        ts = quote.ts.isoformat() if hasattr(quote.ts, "isoformat") else str(quote.ts)
        if latest_ts is None or ts > latest_ts:
            latest_ts = ts
        rows.append(
            PositionDayPnl(
                symbol=sym,
                quantity=qty,
                prev_close=prev,
                current_price=price,
                day_pnl=day_pnl,
                day_pnl_pct=day_pct,
            )
        )

    return TodayPnlResponse(
        total_day_pnl=total, positions=rows, as_of=latest_ts, warnings=warnings
    )


@router.get(
    "/allocation",
    response_model=AllocationResponse,
    summary="Allocation by strategy tag / symbol (research only)",
)
async def get_allocation(
    user: AuthContext = Depends(get_current_user),
    db: SupabaseDB = Depends(get_db),
    cache: Cache = Depends(get_cache),
) -> AllocationResponse:
    account = await _get_default_account(db, user)
    if account is None:
        return AllocationResponse()
    positions = await _load_positions_for_user(db, user, account["id"])
    if not positions:
        return AllocationResponse()

    symbols = [str(p["symbol"]).upper() for p in positions]
    quotes = await market_cache.get_quotes(cache, symbols)
    summary, enriched = portfolio_valuation.compute_summary(positions, quotes)
    total = summary.total_market_value

    by_tag = [
        AllocationSlice(label=tag, value=val, weight=(val / total if total > 0 else None))
        for tag, val in summary.by_strategy_tag.items()
    ]
    by_symbol = [
        AllocationSlice(label=ep.symbol, value=ep.market_value, weight=ep.weight)
        for ep in enriched
        if ep.market_value is not None
    ]
    warnings = list(summary.warnings)
    if total <= 0:
        warnings.append("cache_cold_or_no_market_value")

    return AllocationResponse(
        by_strategy_tag=by_tag,
        by_symbol=by_symbol,
        total_market_value=total,
        as_of=summary.last_marked_at,
        warnings=warnings,
    )


@router.get(
    "/equity-curve",
    response_model=list[EquityPoint],
    summary="Daily NAV history for the default account (forward-only, honest-empty)",
)
async def get_equity_curve(
    start: date | None = Query(
        default=None, description="Inclusive start date (YYYY-MM-DD); omit for all history"
    ),
    end: date | None = Query(
        default=None, description="Inclusive end date (YYYY-MM-DD); omit for through-latest"
    ),
    user: AuthContext = Depends(get_current_user),
    db: SupabaseDB = Depends(get_db),
) -> list[EquityPoint]:
    """Read-only, ascending by date. Returns only days actually snapshotted into
    ``portfolio_equity_snapshots`` — never synthesises NAV. ``start``/``end`` is a
    true calendar window; omit both for full history. Empty list until the writer
    (POST /portfolio/snapshots/run) has recorded a matching day."""
    if start is not None and end is not None and start > end:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="start must be <= end."
        )
    account = await _get_default_account(db, user)
    if account is None:
        return []
    return await portfolio_snapshots.load_curve(
        db,
        user,
        account["id"],
        start=start.isoformat() if start else None,
        end=end.isoformat() if end else None,
    )


@router.post(
    "/snapshots/run",
    response_model=EquitySnapshotRunResult,
    summary="Record today's NAV snapshot for the default account (idempotent per day)",
)
async def run_equity_snapshot(
    user: AuthContext = Depends(get_current_user),
    db: SupabaseDB = Depends(get_db),
    cache: Cache = Depends(get_cache),
) -> EquitySnapshotRunResult:
    """Writer trigger for the equity curve. Auth: the caller's own JWT — the
    dashboard fires this on mount and an external cron can call it with a
    user token. Records at most one snapshot per account per trading day; a
    repeat call the same day recomputes the existing row. No orders, no
    trading — pure NAV valuation persistence."""
    account = await _get_default_account(db, user)
    if account is None:
        return EquitySnapshotRunResult(recorded=False, reason="no_account")
    try:
        result = await portfolio_snapshots.record_daily_snapshot(
            db, user, cache, account["id"]
        )
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    return EquitySnapshotRunResult(
        recorded=result["recorded"],
        reason=result["reason"],
        snapshot_date=result["snapshot_date"],
        total_equity=result["total_equity"],
        warnings=result["warnings"],
    )


# Mirrors api/routes/market.py — the regime is cached there for 60s.
_REGIME_CACHE_KEY = "market:regime"


@router.get(
    "/risk-score",
    response_model=RiskScoreResult,
    summary="Explainable, read-only portfolio risk score (partial-aware)",
)
async def get_risk_score(
    user: AuthContext = Depends(get_current_user),
    db: SupabaseDB = Depends(get_db),
    cache: Cache = Depends(get_cache),
    settings: Settings = Depends(get_settings),
) -> RiskScoreResult:
    """Read-only analytics — NOT trading risk and no order path. Blends only the
    real-data components that are available (concentration, cash buffer, regime
    exposure, drawdown, volatility); liquidity is unavailable until an ADV
    baseline exists. Never fabricates a number."""
    account = await _get_default_account(db, user)
    params = RiskParams(
        w_concentration=settings.risk_weight_concentration,
        w_cash_buffer=settings.risk_weight_cash_buffer,
        w_regime=settings.risk_weight_regime,
        w_drawdown=settings.risk_weight_drawdown,
        w_volatility=settings.risk_weight_volatility,
        target_cash_ratio=settings.risk_target_cash_ratio,
        drawdown_cap=settings.risk_drawdown_cap,
        volatility_cap=settings.risk_volatility_cap,
        min_history_points=settings.risk_min_history_points,
        trading_days_per_year=settings.risk_trading_days_per_year,
    )
    if account is None:
        return portfolio_risk.compute_risk_score(
            position_weights=[], total_market_value=0.0, cash=0.0, total_equity=0.0,
            regime_label=None, nav_history=[], as_of=None, params=params,
        )

    # Valuation (positions × live quotes) → weights + market value.
    total_mv = 0.0
    weights: list[float] = []
    as_of: str | None = None
    positions = await _load_positions_for_user(db, user, account["id"])
    if positions:
        symbols = [str(p["symbol"]).upper() for p in positions]
        quotes = await market_cache.get_quotes(cache, symbols)
        summary, enriched = portfolio_valuation.compute_summary(positions, quotes)
        total_mv = summary.total_market_value
        weights = [ep.weight for ep in enriched if ep.weight is not None]
        as_of = summary.last_marked_at

    # Cash component of NAV (same definition as /assets/summary.total_equity).
    cash_rows = await db.select(
        "cash_balances", where={"account_id": account["id"]}, user_jwt=user.raw_token
    )
    if cash_rows:
        r = cash_rows[0]
        cash = (
            float(r.get("settled_cash") or 0.0)
            + float(r.get("pending_cash") or 0.0)
            + float(r.get("advanced_cash") or 0.0)
            - float(r.get("cash_advance_liability") or 0.0)
        )
    else:
        cash = 0.0
    total_equity = cash + total_mv

    # Market regime — read the cheap cached value (no SSI call here).
    cached_regime = await cache.get_json(_REGIME_CACHE_KEY)
    regime_label = (
        cached_regime.get("label") if isinstance(cached_regime, dict) else None
    )
    if regime_label == "NO_DATA":
        regime_label = None

    # NAV history for drawdown / volatility (forward-only snapshots).
    curve = await portfolio_snapshots.load_curve(db, user, account["id"])
    nav_history = [p.equity for p in curve]
    if as_of is None and curve:
        as_of = curve[-1].ts

    return portfolio_risk.compute_risk_score(
        position_weights=weights,
        total_market_value=total_mv,
        cash=cash,
        total_equity=total_equity,
        regime_label=regime_label,
        nav_history=nav_history,
        as_of=as_of,
        params=params,
    )


@router.get(
    "/positions",
    response_model=list[EnrichedPosition],
    summary="Enriched positions for the default account",
)
async def list_enriched_positions(
    user: AuthContext = Depends(get_current_user),
    db: SupabaseDB = Depends(get_db),
    cache: Cache = Depends(get_cache),
) -> list[EnrichedPosition]:
    account = await _get_default_account(db, user)
    if account is None:
        return []
    positions = await _load_positions_for_user(db, user, account["id"])
    if not positions:
        return []
    symbols = [str(p["symbol"]).upper() for p in positions]
    quotes = await market_cache.get_quotes(cache, symbols)
    _, enriched = portfolio_valuation.compute_summary(positions, quotes)
    return enriched


@router.post(
    "/positions",
    response_model=ManualPosition,
    status_code=status.HTTP_201_CREATED,
    summary="Add a position to the default account (auto-creates one on first use)",
)
async def create_position_default(
    payload: PositionCreate,
    user: AuthContext = Depends(get_current_user),
    db: SupabaseDB = Depends(get_db),
) -> ManualPosition:
    account = await _get_default_account(db, user, create_if_missing=True)
    if account is None:
        # Should never happen — create_if_missing=True guarantees a row.
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not resolve default account.",
        )
    try:
        row = await db.insert(
            "manual_positions",
            {
                "account_id": account["id"],
                "symbol": payload.symbol.upper(),
                "exchange": payload.exchange,
                "quantity": payload.quantity,
                "avg_cost": payload.avg_cost,
                "strategy_tag": payload.strategy_tag,
                "note": payload.note,
            },
            user_jwt=user.raw_token,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    return ManualPosition.model_validate(row)


@router.put(
    "/positions/{position_id}",
    response_model=ManualPosition,
    summary="Update a position on the default account",
)
async def update_position_default(
    position_id: str,
    payload: PositionUpdate,
    user: AuthContext = Depends(get_current_user),
    db: SupabaseDB = Depends(get_db),
) -> ManualPosition:
    patch = payload.model_dump(exclude_none=True)
    if "symbol" in patch:
        patch["symbol"] = patch["symbol"].upper()
    if not patch:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Empty update payload."
        )
    rows = await db.update(
        "manual_positions",
        patch,
        where={"id": position_id},
        user_jwt=user.raw_token,
    )
    if not rows:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Position not found."
        )
    return ManualPosition.model_validate(rows[0])


@router.delete(
    "/positions/{position_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a position on the default account",
)
async def delete_position_default(
    position_id: str,
    user: AuthContext = Depends(get_current_user),
    db: SupabaseDB = Depends(get_db),
) -> None:
    deleted = await db.delete(
        "manual_positions",
        where={"id": position_id},
        user_jwt=user.raw_token,
    )
    if deleted == 0:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Position not found."
        )


def _mask_account(account_no: str) -> str:
    """Show only the last 4 chars of the broker account number."""
    tail = account_no[-4:] if account_no else ""
    return f"••••{tail}" if tail else "••••"


@router.post(
    "/sync/ssi",
    response_model=SsiAccountSnapshot,
    summary="Read-only SSI account snapshot (status + cash + positions). No orders.",
)
async def sync_ssi_readonly(
    user: AuthContext = Depends(get_current_user),
    provider: TradingProvider = Depends(get_trading_provider),
    settings: Settings = Depends(get_settings),
) -> SsiAccountSnapshot:
    """Aggregate the user's READ-ONLY SSI account state in one call.

    Read-only by construction: it never writes to the DB and never touches an
    order path (``submit_order`` stays 501). The SSI account is resolved
    SERVER-SIDE from ``ssi_trading_account_no`` — never from client input — so
    there is no account-id injection / RLS surface. Real cash + positions appear
    only when the provider is a genuinely configured read-only SSI connection;
    in mock/dev or when unconfigured, ``connected=False`` and no fabricated
    balances are returned. Always 200 (auth-gated) so the panel renders a calm
    state rather than throwing.
    """
    snap = await provider.status()
    live = (not snap.mock) and snap.status_code == "READ_ONLY"
    if not live:
        return SsiAccountSnapshot(
            connected=False,
            status_code=snap.status_code,
            mock=snap.mock,
            note=snap.note,
        )

    account_ref = settings.ssi_trading_account_no
    try:
        cash = await provider.get_cash_balance(account_ref)
        positions = await provider.get_stock_positions(account_ref)
    except TradingProviderError as exc:
        # Honest failure — never fabricate. Surface a sanitized status.
        return SsiAccountSnapshot(
            connected=False,
            status_code="ERROR",
            mock=False,
            note=exc.client_safe_message,
        )

    return SsiAccountSnapshot(
        connected=True,
        status_code="READ_ONLY",
        mock=False,
        account_masked=_mask_account(account_ref),
        cash=cash,
        positions=positions,
        note=snap.note,
    )
