"""Paper-trading orchestrator.

Wires together: market data lookup, fill calculator, ledger, audit.
The route layer calls one of these top-level functions per HTTP path
to keep handlers thin.
"""

from __future__ import annotations

from typing import Any

from core.security import AuthContext
from providers.market_data import MarketDataProvider, ProviderError
from schemas.paper_trading import OrderType, Side, SourceType
from services.paper_execution import (
    FillInputs,
    RejectionResult,
    simulate_fill,
)
from services.paper_ledger import (
    apply_fill,
    get_current_cash,
)
from services.supabase_db import SupabaseDB


async def _fetch_execution_context(
    provider: MarketDataProvider, symbol: str
) -> tuple[float | None, int, float | None, float | None, bool]:
    """Return (price, lot_size, ceiling, floor, symbol_active).

    ``price`` is None when the provider fails — caller must mark
    DATA_UNAVAILABLE rather than fall back to a fake number.
    """
    price: float | None = None
    lot_size = 100
    ceiling: float | None = None
    floor: float | None = None
    symbol_active = True

    try:
        quotes = await provider.get_latest_quotes([symbol])
        if quotes:
            q = quotes[0]
            price = float(q.price) if q.price else None
            ceiling = q.ceiling_price
            floor = q.floor_price
    except ProviderError:
        price = None  # signal DATA_UNAVAILABLE

    try:
        sec = await provider.get_security_details(symbol)
        if sec.lot_size:
            lot_size = sec.lot_size
        if sec.status and sec.status != "ACTIVE":
            symbol_active = False
    except ProviderError:
        # Security details optional; lot defaults to 100. If sec lookup
        # fails it does NOT downgrade to DATA_UNAVAILABLE — only the
        # price does.
        pass

    return price, lot_size, ceiling, floor, symbol_active


async def simulate_paper_order(
    *,
    db: SupabaseDB,
    user: AuthContext,
    provider: MarketDataProvider,
    paper_account_id: str,
    symbol: str,
    side: Side,
    order_type: OrderType,
    quantity: int,
    limit_price: float | None,
    source_type: SourceType,
    source_id: str | None,
) -> tuple[dict[str, Any], dict[str, Any] | None, str | None]:
    """Execute a simulated paper order. Returns (order_row, fill_row|None, rejection|None).

    The order row is ALWAYS persisted (audit). Fill row is None when
    the order is rejected.
    """
    sym = symbol.upper()
    market_price, lot_size, ceiling, floor, active = await _fetch_execution_context(
        provider, sym
    )

    # Decide execution price.
    #
    # Phase 2.7 review fix (CRITICAL):
    # Previously this used ``min(limit, market)`` for BOTH sides — which
    # silently filled SELL LIMITs at a worse price than the user asked
    # for (e.g. SELL LIMIT 110 with market=100 filled at 100). Correct
    # per-side semantics:
    #   BUY LIMIT:  fill at min(limit, market)
    #   SELL LIMIT: fill at max(limit, market)
    # Both choose the user-favourable side of the spread, mirroring how
    # a real limit order would behave when it crosses.
    if order_type == "MARKET":
        execution_price = market_price
    else:  # LIMIT
        if limit_price is not None and market_price is not None:
            execution_price = (
                min(limit_price, market_price) if side == "BUY"
                else max(limit_price, market_price)
            )
        elif limit_price is not None:
            execution_price = limit_price
        else:
            execution_price = market_price

    # DATA_UNAVAILABLE: no fake price fallback in production.
    if execution_price is None:
        order = await _persist_order(
            db, user, paper_account_id, sym, side, order_type,
            quantity, limit_price, source_type, source_id,
            status="REJECTED", rejection_reason="DATA_UNAVAILABLE",
        )
        return order, None, "DATA_UNAVAILABLE"

    buying_power = await get_current_cash(db, user, paper_account_id)
    sellable = await _sellable_quantity(db, user, paper_account_id, sym)

    result = simulate_fill(
        FillInputs(
            side=side,
            quantity=quantity,
            fill_price=execution_price,
            lot_size=lot_size,
            ceiling_price=ceiling,
            floor_price=floor,
            buying_power=buying_power,
            sellable_quantity=sellable,
            symbol_active=active,
        )
    )

    if isinstance(result, RejectionResult):
        order = await _persist_order(
            db, user, paper_account_id, sym, side, order_type,
            quantity, limit_price, source_type, source_id,
            status="REJECTED", rejection_reason=result.reason,
        )
        return order, None, result.reason

    # Persist as SUBMITTED then immediately mark FILLED — paper-trading
    # has no queue.
    order = await _persist_order(
        db, user, paper_account_id, sym, side, order_type,
        quantity, limit_price, source_type, source_id,
        status="SUBMITTED", rejection_reason=None,
    )
    fill_row = await apply_fill(
        db, user, paper_account_id,
        order_id=order["id"], symbol=sym, fill=result,
    )
    updated_order = await db.update(
        "paper_orders",
        {"status": "FILLED"},
        where={"id": order["id"]},
        user_jwt=user.raw_token,
    )
    order_row = updated_order[0] if updated_order else order
    return order_row, fill_row, None


async def _persist_order(
    db: SupabaseDB,
    user: AuthContext,
    paper_account_id: str,
    symbol: str,
    side: Side,
    order_type: OrderType,
    quantity: int,
    limit_price: float | None,
    source_type: SourceType,
    source_id: str | None,
    *,
    status: str,
    rejection_reason: str | None,
) -> dict[str, Any]:
    return await db.insert(
        "paper_orders",
        {
            "user_id": user.user_id,
            "paper_account_id": paper_account_id,
            "source_type": source_type,
            "source_id": source_id,
            "symbol": symbol,
            "side": side,
            "order_type": order_type,
            "quantity": quantity,
            "limit_price": limit_price,
            "status": status,
            "rejection_reason": rejection_reason,
        },
        user_jwt=user.raw_token,
    )


async def _sellable_quantity(
    db: SupabaseDB, user: AuthContext, account_id: str, symbol: str
) -> int:
    rows = await db.select(
        "paper_positions",
        where={"paper_account_id": account_id, "symbol": symbol},
        user_jwt=user.raw_token,
    )
    if not rows:
        return 0
    return int(rows[0].get("sellable_quantity") or 0)
