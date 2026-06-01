"""Phase 2.7 Paper-trading routes.

Simulated only. No broker contact. All cash + share movements happen in
the paper_* tables; the only external call is for live market prices
via ``MarketDataProvider.get_latest_quotes`` (which is the existing
SSI/mock provider).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status

from core.deps import get_db, get_market_provider
from core.logging import get_logger
from core.security import AuthContext, get_current_user
from providers.market_data import MarketDataProvider, ProviderError
from schemas.paper_trading import (
    PaperAccount,
    PaperAccountCreate,
    PaperAccountSummary,
    PaperAuditAction,
    PaperCashLedgerEntry,
    PaperEquityPoint,
    PaperFill,
    PaperOrder,
    PaperOrderCreate,
    PaperOrderResult,
    PaperPosition,
    RunRecommendationRequest,
)
from services import paper_trading as paper_orchestrator
from services.paper_ledger import (
    get_current_cash,
    get_pending_cash,
    settle_pending,
)
from services.paper_performance import compute_snapshot, record_snapshot
from services.supabase_db import SupabaseDB

logger = get_logger(__name__)
router = APIRouter()


# ── Helpers ─────────────────────────────────────────────────────────────────


async def _audit(
    db: SupabaseDB,
    user: AuthContext,
    action: PaperAuditAction,
    request: Request | None,
    account_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    logger.info(
        "paper.audit user=%s action=%s account=%s",
        user.user_id, action, account_id,
    )
    try:
        await db.insert(
            "paper_audit_logs",
            {
                "user_id": user.user_id,
                "paper_account_id": account_id,
                "action": action,
                "metadata": metadata or {},
            },
            user_jwt=user.raw_token,
        )
    except Exception as exc:  # pragma: no cover
        logger.warning("paper.audit_persist_failed action=%s err=%s", action, type(exc).__name__)


async def _resolve_account(
    db: SupabaseDB, user: AuthContext, account_id: str
) -> dict[str, Any]:
    rows = await db.select(
        "paper_accounts",
        where={"id": account_id, "user_id": user.user_id},
        user_jwt=user.raw_token,
    )
    if not rows:
        raise HTTPException(status_code=404, detail="Paper account not found.")
    return rows[0]


# ── Accounts ───────────────────────────────────────────────────────────────


@router.get("/accounts", response_model=list[PaperAccount])
async def list_accounts(
    user: AuthContext = Depends(get_current_user),
    db: SupabaseDB = Depends(get_db),
) -> list[PaperAccount]:
    rows = await db.select(
        "paper_accounts", where={"user_id": user.user_id}, user_jwt=user.raw_token
    )
    return [PaperAccount(**r) for r in rows]


@router.post(
    "/accounts", response_model=PaperAccount, status_code=status.HTTP_201_CREATED
)
async def create_paper_account(
    payload: PaperAccountCreate,
    request: Request,
    user: AuthContext = Depends(get_current_user),
    db: SupabaseDB = Depends(get_db),
) -> PaperAccount:
    row = await db.insert(
        "paper_accounts",
        {
            "user_id": user.user_id,
            "name": payload.name,
            "starting_cash": payload.starting_cash,
            "current_cash": payload.starting_cash,
            "currency": payload.currency,
        },
        user_jwt=user.raw_token,
    )
    # Seed the cash ledger with a SETTLED deposit row.
    await db.insert(
        "paper_cash_ledger",
        {
            "user_id": user.user_id,
            "paper_account_id": row["id"],
            "event_type": "DEPOSIT",
            "amount": payload.starting_cash,
            "settled_date": (row.get("created_at") or "").split("T")[0] or "1970-01-01",
            "status": "SETTLED",
            "metadata": {"source": "create_account"},
        },
        user_jwt=user.raw_token,
    )
    await _audit(
        db, user, "PAPER_ACCOUNT_CREATED", request,
        account_id=row["id"], metadata={"starting_cash": payload.starting_cash},
    )
    return PaperAccount(**row)


@router.get("/accounts/{account_id}", response_model=PaperAccount)
async def get_account(
    account_id: str,
    user: AuthContext = Depends(get_current_user),
    db: SupabaseDB = Depends(get_db),
) -> PaperAccount:
    row = await _resolve_account(db, user, account_id)
    return PaperAccount(**row)


# ── Read-side: summary / positions / orders / fills / equity ───────────────


async def _mark_prices(
    provider: MarketDataProvider, symbols: list[str]
) -> dict[str, float]:
    out: dict[str, float] = {}
    if not symbols:
        return out
    try:
        quotes = await provider.get_latest_quotes(list({s for s in symbols}))
        for q in quotes:
            if q.price:
                out[q.symbol.upper()] = float(q.price)
    except ProviderError:
        pass
    return out


@router.get(
    "/accounts/{account_id}/summary", response_model=PaperAccountSummary
)
async def account_summary(
    account_id: str,
    user: AuthContext = Depends(get_current_user),
    db: SupabaseDB = Depends(get_db),
    provider: MarketDataProvider = Depends(get_market_provider),
) -> PaperAccountSummary:
    acc_row = await _resolve_account(db, user, account_id)
    await settle_pending(db, user, account_id)
    positions = await db.select(
        "paper_positions",
        where={"paper_account_id": account_id},
        user_jwt=user.raw_token,
    )
    symbols = [p["symbol"] for p in positions]
    marks = await _mark_prices(provider, symbols)
    data_status = "FRESH" if marks or not symbols else "DATA_UNAVAILABLE"
    snap = await compute_snapshot(
        db, user, account_id,
        starting_cash=float(acc_row.get("starting_cash") or 0.0),
        mark_prices=marks,
    )
    open_orders_rows = await db.select(
        "paper_orders",
        where={"paper_account_id": account_id, "status": "SUBMITTED"},
        user_jwt=user.raw_token,
    )
    # Refresh position rows after compute_snapshot's materialise.
    positions = await db.select(
        "paper_positions",
        where={"paper_account_id": account_id},
        user_jwt=user.raw_token,
    )
    return PaperAccountSummary(
        account=PaperAccount(**acc_row),
        cash=snap.cash,
        pending_cash=snap.pending_cash,
        stock_value=snap.stock_value,
        total_equity=snap.total_equity,
        realized_pnl=snap.realized_pnl,
        unrealized_pnl=snap.unrealized_pnl,
        drawdown=snap.drawdown,
        open_orders=len(open_orders_rows),
        positions=[PaperPosition(**p) for p in positions],
        data_status=data_status,
    )


@router.get(
    "/accounts/{account_id}/positions", response_model=list[PaperPosition]
)
async def list_positions(
    account_id: str,
    user: AuthContext = Depends(get_current_user),
    db: SupabaseDB = Depends(get_db),
) -> list[PaperPosition]:
    await _resolve_account(db, user, account_id)
    await settle_pending(db, user, account_id)
    rows = await db.select(
        "paper_positions",
        where={"paper_account_id": account_id},
        user_jwt=user.raw_token,
    )
    return [PaperPosition(**r) for r in rows]


@router.get(
    "/accounts/{account_id}/orders", response_model=list[PaperOrder]
)
async def list_orders(
    account_id: str,
    user: AuthContext = Depends(get_current_user),
    db: SupabaseDB = Depends(get_db),
) -> list[PaperOrder]:
    await _resolve_account(db, user, account_id)
    rows = await db.select(
        "paper_orders",
        where={"paper_account_id": account_id},
        user_jwt=user.raw_token,
    )
    rows.sort(key=lambda r: r.get("created_at") or "", reverse=True)
    return [PaperOrder(**r) for r in rows]


@router.get("/accounts/{account_id}/fills", response_model=list[PaperFill])
async def list_fills(
    account_id: str,
    user: AuthContext = Depends(get_current_user),
    db: SupabaseDB = Depends(get_db),
) -> list[PaperFill]:
    await _resolve_account(db, user, account_id)
    rows = await db.select(
        "paper_fills",
        where={"paper_account_id": account_id},
        user_jwt=user.raw_token,
    )
    rows.sort(key=lambda r: r.get("filled_at") or "", reverse=True)
    return [PaperFill(**r) for r in rows]


@router.get(
    "/accounts/{account_id}/equity-curve",
    response_model=list[PaperEquityPoint],
)
async def equity_curve(
    account_id: str,
    user: AuthContext = Depends(get_current_user),
    db: SupabaseDB = Depends(get_db),
    provider: MarketDataProvider = Depends(get_market_provider),
) -> list[PaperEquityPoint]:
    acc_row = await _resolve_account(db, user, account_id)
    await settle_pending(db, user, account_id, audit_request=None)
    # Phase 2.7 review fix: do NOT append a snapshot on every GET — the
    # equity_curve table would balloon under polling. Throttle to ≥60s
    # since the last recorded snapshot.
    existing = await db.select(
        "paper_equity_curve",
        where={"paper_account_id": account_id},
        user_jwt=user.raw_token,
    )
    existing.sort(key=lambda r: r.get("timestamp") or "")
    should_append = True
    if existing:
        last_ts = existing[-1].get("timestamp")
        if isinstance(last_ts, str):
            try:
                last_dt = datetime.fromisoformat(last_ts.replace("Z", "+00:00"))
                if (datetime.now(timezone.utc) - last_dt).total_seconds() < 60:
                    should_append = False
            except ValueError:
                pass
    if should_append:
        positions = await db.select(
            "paper_positions",
            where={"paper_account_id": account_id},
            user_jwt=user.raw_token,
        )
        marks = await _mark_prices(provider, [p["symbol"] for p in positions])
        snap = await compute_snapshot(
            db, user, account_id,
            starting_cash=float(acc_row.get("starting_cash") or 0.0),
            mark_prices=marks,
        )
        await record_snapshot(db, user, account_id, snap)
        existing = await db.select(
            "paper_equity_curve",
            where={"paper_account_id": account_id},
            user_jwt=user.raw_token,
        )
        existing.sort(key=lambda r: r.get("timestamp") or "")
    return [PaperEquityPoint(**r) for r in existing]


# ── Order submission ──────────────────────────────────────────────────────


@router.post(
    "/accounts/{account_id}/orders", response_model=PaperOrderResult
)
async def submit_paper_order(
    account_id: str,
    payload: PaperOrderCreate,
    request: Request,
    user: AuthContext = Depends(get_current_user),
    db: SupabaseDB = Depends(get_db),
    provider: MarketDataProvider = Depends(get_market_provider),
) -> PaperOrderResult:
    await _resolve_account(db, user, account_id)
    await settle_pending(db, user, account_id)
    order_row, fill_row, rejection = await paper_orchestrator.simulate_paper_order(
        db=db, user=user, provider=provider,
        paper_account_id=account_id,
        symbol=payload.symbol, side=payload.side,
        order_type=payload.order_type, quantity=payload.quantity,
        limit_price=payload.limit_price,
        source_type=payload.source_type, source_id=payload.source_id,
    )
    if rejection:
        await _audit(
            db, user, "PAPER_ORDER_REJECTED", request,
            account_id=account_id,
            metadata={
                "symbol": payload.symbol, "side": payload.side,
                "reason": rejection,
            },
        )
    else:
        await _audit(
            db, user, "PAPER_ORDER_FILLED", request,
            account_id=account_id,
            metadata={
                "order_id": order_row["id"], "symbol": payload.symbol,
                "side": payload.side, "quantity": payload.quantity,
            },
        )
    return PaperOrderResult(
        order=PaperOrder(**order_row),
        fill=PaperFill(**fill_row) if fill_row else None,
        rejection_reason=rejection,
    )


@router.post("/accounts/{account_id}/orders/{order_id}/cancel")
async def cancel_order(
    account_id: str,
    order_id: str,
    request: Request,
    user: AuthContext = Depends(get_current_user),
    db: SupabaseDB = Depends(get_db),
) -> dict[str, Any]:
    """Cancel an open paper order. FILLED orders cannot be cancelled.

    Phase 2.7 review fix (CRITICAL IDOR): the SELECT and UPDATE both
    constrain by ``paper_account_id == account_id`` so a user with two
    paper accounts cannot cancel order X (in account B) via account A's
    URL. Previously only ``user_id`` was checked, allowing the audit
    trail to be misattributed AND the wrong account's order to be hit.
    """
    await _resolve_account(db, user, account_id)
    rows = await db.select(
        "paper_orders",
        where={
            "id": order_id,
            "user_id": user.user_id,
            "paper_account_id": account_id,
        },
        user_jwt=user.raw_token,
    )
    if not rows:
        raise HTTPException(status_code=404, detail="Order not found.")
    row = rows[0]
    if row["status"] in ("FILLED", "CANCELLED", "REJECTED"):
        # Phase 2.7 review fix: previously this returned silently with no
        # audit trail. Failed cancel attempts must leave a record.
        await _audit(
            db, user, "PAPER_ORDER_CANCEL_REJECTED", request,
            account_id=account_id,
            metadata={
                "order_id": order_id,
                "current_status": row["status"],
            },
        )
        return {"ok": False, "reason": f"NOT_CANCELLABLE_STATE_{row['status']}"}
    await db.update(
        "paper_orders",
        {"status": "CANCELLED"},
        where={
            "id": order_id,
            "user_id": user.user_id,
            "paper_account_id": account_id,
        },
        user_jwt=user.raw_token,
    )
    await _audit(
        db, user, "PAPER_ORDER_CANCELLED", request,
        account_id=account_id, metadata={"order_id": order_id},
    )
    return {"ok": True}


# ── Recommendation + strategy placeholder ─────────────────────────────────


@router.post(
    "/accounts/{account_id}/run-recommendation",
    response_model=PaperOrderResult,
)
async def run_recommendation(
    account_id: str,
    payload: RunRecommendationRequest,
    request: Request,
    user: AuthContext = Depends(get_current_user),
    db: SupabaseDB = Depends(get_db),
    provider: MarketDataProvider = Depends(get_market_provider),
) -> PaperOrderResult:
    """Simulate a paper order driven by a recommendation. The
    recommendation's structured fields (symbol, side, qty, limit) come
    in as the request body — this route does NOT re-query the
    recommendation engine because the user already inspected it."""
    await _resolve_account(db, user, account_id)
    await settle_pending(db, user, account_id)
    order_row, fill_row, rejection = await paper_orchestrator.simulate_paper_order(
        db=db, user=user, provider=provider,
        paper_account_id=account_id,
        symbol=payload.symbol, side=payload.side,
        order_type="LIMIT" if payload.limit_price else "MARKET",
        quantity=payload.quantity, limit_price=payload.limit_price,
        source_type="RECOMMENDATION", source_id=payload.recommendation_id,
    )
    await _audit(
        db, user, "PAPER_RECOMMENDATION_RUN", request,
        account_id=account_id,
        metadata={
            "symbol": payload.symbol, "rejection": rejection,
            "recommendation_id": payload.recommendation_id,
        },
    )
    return PaperOrderResult(
        order=PaperOrder(**order_row),
        fill=PaperFill(**fill_row) if fill_row else None,
        rejection_reason=rejection,
    )


@router.post("/accounts/{account_id}/run-strategy-placeholder")
async def run_strategy_placeholder(
    account_id: str,
    request: Request,
    user: AuthContext = Depends(get_current_user),
    db: SupabaseDB = Depends(get_db),
) -> dict[str, Any]:
    """Placeholder for Phase 2.8 strategy runner. Does nothing but
    leaves an audit row so the UI can hint at the future flow."""
    await _resolve_account(db, user, account_id)
    await _audit(
        db, user, "PAPER_STRATEGY_RUN_PLACEHOLDER", request,
        account_id=account_id,
        metadata={"note": "Strategy engine arrives in Phase 2.8"},
    )
    return {"ok": True, "next_step": "Phase 2.8 will wire a strategy runner."}
