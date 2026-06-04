"""Assets + PnL routes.

Sits on top of ``manual_portfolio_accounts`` (default-account rule), the new
``cash_balances`` + ``trade_transactions`` tables, and the live quote cache.

All numbers are read-only research output. No order placement happens here.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, Query

from core.deps import get_cache, get_db
from core.security import AuthContext, get_current_user
from schemas.assets import (
    AssetsSummary,
    CashBalance,
    CostBreakdown,
    CostPeriod,
    PnlBreakdown,
    PnlWaterfall,
)
from services import market_cache, portfolio_valuation
from services.cache import Cache
from services.supabase_db import SupabaseDB

router = APIRouter()


# ── Helpers (mirrors the default-account rule from portfolio.py) ─────────────


async def _get_default_account_row(
    db: SupabaseDB, user: AuthContext
) -> dict[str, Any] | None:
    accounts = await db.select(
        "manual_portfolio_accounts",
        where={"user_id": user.user_id},
        user_jwt=user.raw_token,
    )
    if not accounts:
        return None
    return sorted(
        accounts, key=lambda a: a.get("created_at") or a.get("id", "")
    )[0]


def _empty_cash(account_id: str | None) -> CashBalance:
    return CashBalance(
        account_id=account_id or "",
        as_of=datetime.now(UTC).isoformat(),
    )


async def _read_cash_balance(
    db: SupabaseDB, user: AuthContext, account_id: str
) -> CashBalance:
    rows = await db.select(
        "cash_balances",
        where={"account_id": account_id},
        user_jwt=user.raw_token,
    )
    if not rows:
        # Brief says: only auto-init zero-row when explicitly asked. /assets/summary
        # asks explicitly, so we materialize a zero row before returning. RLS will
        # reject this if the user does not own the account.
        try:
            await db.insert(
                "cash_balances",
                {"account_id": account_id},
                user_jwt=user.raw_token,
            )
        except PermissionError:
            # User can't touch this account; just hand back an in-memory zero row.
            return _empty_cash(account_id)
        return _empty_cash(account_id)
    row = rows[0]
    return CashBalance(
        account_id=row["account_id"],
        settled_cash=float(row.get("settled_cash") or 0),
        pending_cash=float(row.get("pending_cash") or 0),
        advanced_cash=float(row.get("advanced_cash") or 0),
        cash_advance_liability=float(row.get("cash_advance_liability") or 0),
        withdrawable_cash=float(row.get("withdrawable_cash") or 0),
        currency=row.get("currency") or "VND",
        as_of=row.get("as_of") or row.get("updated_at"),
    )


async def _load_positions(
    db: SupabaseDB, user: AuthContext, account_id: str
) -> list[dict[str, Any]]:
    return await db.select(
        "manual_positions",
        where={"account_id": account_id},
        user_jwt=user.raw_token,
    )


async def _load_trades(
    db: SupabaseDB, user: AuthContext, account_id: str
) -> list[dict[str, Any]]:
    return await db.select(
        "trade_transactions",
        where={"account_id": account_id},
        user_jwt=user.raw_token,
    )


# ── Routes ───────────────────────────────────────────────────────────────────


@router.get(
    "/summary",
    response_model=AssetsSummary,
    summary="Cash + equity rollup (research only — not financial advice)",
)
async def get_assets_summary(
    user: AuthContext = Depends(get_current_user),
    db: SupabaseDB = Depends(get_db),
    cache: Cache = Depends(get_cache),
) -> AssetsSummary:
    account = await _get_default_account_row(db, user)
    if account is None:
        cash = _empty_cash(None)
        return AssetsSummary(cash=cash)

    cash = await _read_cash_balance(db, user, account["id"])
    positions = await _load_positions(db, user, account["id"])

    stock_value = 0.0
    warnings: list[str] = []
    if positions:
        symbols = [str(p["symbol"]).upper() for p in positions]
        quotes = await market_cache.get_quotes(cache, symbols)
        summary, _ = portfolio_valuation.compute_summary(positions, quotes)
        stock_value = summary.total_market_value
        warnings = summary.warnings

    total_equity = (
        cash.settled_cash
        + cash.pending_cash
        + stock_value
        + cash.advanced_cash
        - cash.cash_advance_liability
    )
    # Phase 1 conservative: only settled cash is true buying power.
    buying_power = cash.settled_cash

    return AssetsSummary(
        account_id=account["id"],
        cash=cash,
        stock_market_value=stock_value,
        total_equity=total_equity,
        available_buying_power=buying_power,
        currency=cash.currency,
        warnings=warnings,
    )


@router.get(
    "/pnl",
    summary="Realized + unrealized PnL with per-symbol breakdown",
)
async def get_pnl(
    user: AuthContext = Depends(get_current_user),
    db: SupabaseDB = Depends(get_db),
    cache: Cache = Depends(get_cache),
) -> dict[str, Any]:
    account = await _get_default_account_row(db, user)
    if account is None:
        empty = PnlBreakdown()
        return {
            "realized": empty.model_dump(),
            "unrealized": empty.model_dump(),
            "total": empty.model_dump(),
            "by_symbol": [],
            "disclaimer": "Research only — not financial advice. No orders placed.",
        }

    positions = await _load_positions(db, user, account["id"])
    trades = await _load_trades(db, user, account["id"])

    # Unrealized
    enriched_list = []
    summary_unrealized = 0.0
    summary_cost = 0.0
    if positions:
        symbols = [str(p["symbol"]).upper() for p in positions]
        quotes = await market_cache.get_quotes(cache, symbols)
        summary, enriched_list = portfolio_valuation.compute_summary(positions, quotes)
        summary_unrealized = summary.total_unrealized_pnl
        summary_cost = summary.total_cost_basis

    # Realized
    realized = portfolio_valuation.realized_pnl_from_trades(trades)
    total_realized = float(realized.get("total_realized", 0.0))

    realized_cost = sum(
        float(v.get("cost_basis_at_sell", 0.0))
        for v in (realized.get("by_symbol") or {}).values()
    )

    def _pct(amount: float, cost: float) -> float | None:
        return (amount / cost) if cost > 0 else None

    realized_block = PnlBreakdown(
        amount=total_realized,
        cost_basis=realized_cost,
        return_pct=_pct(total_realized, realized_cost),
    )
    unrealized_block = PnlBreakdown(
        amount=summary_unrealized,
        cost_basis=summary_cost,
        return_pct=_pct(summary_unrealized, summary_cost),
    )
    total_amount = total_realized + summary_unrealized
    total_cost = realized_cost + summary_cost
    total_block = PnlBreakdown(
        amount=total_amount,
        cost_basis=total_cost,
        return_pct=_pct(total_amount, total_cost),
    )

    by_symbol = portfolio_valuation.build_pnl_by_symbol(enriched_list, realized)

    return {
        "realized": realized_block.model_dump(),
        "unrealized": unrealized_block.model_dump(),
        "total": total_block.model_dump(),
        "by_symbol": [row.model_dump() for row in by_symbol],
        "disclaimer": "Research only — not financial advice. No orders placed.",
    }


@router.get(
    "/pnl/waterfall",
    response_model=PnlWaterfall,
    summary="Ordered PnL contribution series: Realized → Unrealized → Costs → Net",
)
async def get_pnl_waterfall(
    user: AuthContext = Depends(get_current_user),
    db: SupabaseDB = Depends(get_db),
    cache: Cache = Depends(get_cache),
) -> PnlWaterfall:
    account = await _get_default_account_row(db, user)
    if account is None:
        return PnlWaterfall()  # honest-empty: buckets []

    positions = await _load_positions(db, user, account["id"])
    trades = await _load_trades(db, user, account["id"])

    # Honest-empty when the account has neither trades nor positions: no bars
    # instead of four zeros (mirrors PnlWaterfall.tsx `data.length === 0`).
    if not positions and not trades:
        return PnlWaterfall()

    # Unrealized (live-marked) — same path as /assets/pnl.
    summary_unrealized = 0.0
    as_of: str | None = None
    if positions:
        symbols = [str(p["symbol"]).upper() for p in positions]
        quotes = await market_cache.get_quotes(cache, symbols)
        summary, _ = portfolio_valuation.compute_summary(positions, quotes)
        summary_unrealized = summary.total_unrealized_pnl
        as_of = summary.last_marked_at

    # Realized is GROSS of fees; costs are the disjoint fee total → no double-count.
    realized = portfolio_valuation.realized_pnl_from_trades(trades)
    total_realized = float(realized.get("total_realized", 0.0))
    costs = portfolio_valuation.cost_breakdown(trades).total

    return portfolio_valuation.build_pnl_waterfall(
        realized=total_realized,
        unrealized=summary_unrealized,
        costs=costs,
        as_of=as_of,
    )


@router.get(
    "/costs",
    response_model=CostBreakdown,
    summary="Brokerage / VAT / sell tax / advance / slippage rollup",
)
async def get_costs(
    period: CostPeriod = Query(default="ALL"),
    user: AuthContext = Depends(get_current_user),
    db: SupabaseDB = Depends(get_db),
) -> CostBreakdown:
    account = await _get_default_account_row(db, user)
    if account is None:
        return CostBreakdown(period=period)
    trades = await _load_trades(db, user, account["id"])
    return portfolio_valuation.cost_breakdown(trades, period=period)
