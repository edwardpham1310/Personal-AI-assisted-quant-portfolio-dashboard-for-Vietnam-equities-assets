"""Paper-trading performance: equity snapshot, PnL, drawdown.

Lightweight — every call reads cash + pending + positions + last
known market price and computes a fresh number. The
``paper_equity_curve`` table accumulates point-in-time snapshots
written by ``record_snapshot``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from core.security import AuthContext
from services.paper_ledger import get_current_cash, get_pending_cash
from services.supabase_db import SupabaseDB


@dataclass(frozen=True)
class EquitySnapshot:
    timestamp: datetime
    cash: float
    pending_cash: float
    stock_value: float
    total_equity: float
    realized_pnl: float
    unrealized_pnl: float
    drawdown: float


async def compute_snapshot(
    db: SupabaseDB,
    user: AuthContext,
    account_id: str,
    *,
    starting_cash: float,
    mark_prices: dict[str, float] | None = None,
    now: datetime | None = None,
) -> EquitySnapshot:
    """Compute the live equity snapshot.

    ``mark_prices`` should map ``symbol → latest SSI price``. If a
    position's symbol is missing from this dict, ``avg_cost`` is used
    as a conservative fallback (zero unrealized PnL on that line)
    rather than zero (which would dramatically overstate drawdown).
    """
    mark_prices = mark_prices or {}
    now = now or datetime.now(UTC)

    cash = await get_current_cash(db, user, account_id)
    pending = await get_pending_cash(db, user, account_id)
    positions = await db.select(
        "paper_positions",
        where={"paper_account_id": account_id},
        user_jwt=user.raw_token,
    )
    stock_value = 0.0
    unrealized = 0.0
    for p in positions:
        qty = int(p.get("quantity") or 0)
        avg = float(p.get("avg_cost") or 0.0)
        mp = mark_prices.get(p["symbol"])
        if mp is None:
            mp = avg
        mv = mp * qty
        stock_value += mv
        unrealized += (mp - avg) * qty
        # Materialise the snapshot back into the position row so the UI
        # can read it without re-running the snapshot math.
        await db.update(
            "paper_positions",
            {"market_price": mp, "market_value": mv, "unrealized_pnl": (mp - avg) * qty},
            where={"id": p["id"]},
            user_jwt=user.raw_token,
        )

    total_equity = cash + pending + stock_value
    realized_pnl = total_equity - starting_cash - unrealized

    # Drawdown vs the best-ever equity across the saved curve.
    curve = await db.select(
        "paper_equity_curve",
        where={"paper_account_id": account_id},
        user_jwt=user.raw_token,
    )
    peak = max(
        [float(r.get("total_equity") or 0.0) for r in curve] + [starting_cash]
    )
    drawdown = 0.0
    if peak > 0 and total_equity < peak:
        drawdown = (peak - total_equity) / peak

    return EquitySnapshot(
        timestamp=now,
        cash=cash,
        pending_cash=pending,
        stock_value=stock_value,
        total_equity=total_equity,
        realized_pnl=realized_pnl,
        unrealized_pnl=unrealized,
        drawdown=drawdown,
    )


async def record_snapshot(
    db: SupabaseDB,
    user: AuthContext,
    account_id: str,
    snap: EquitySnapshot,
) -> dict[str, Any]:
    row = await db.insert(
        "paper_equity_curve",
        {
            "user_id": user.user_id,
            "paper_account_id": account_id,
            "timestamp": snap.timestamp.isoformat(),
            "cash": snap.cash,
            "pending_cash": snap.pending_cash,
            "stock_value": snap.stock_value,
            "total_equity": snap.total_equity,
            "drawdown": snap.drawdown,
        },
        user_jwt=user.raw_token,
    )
    return dict(row)
