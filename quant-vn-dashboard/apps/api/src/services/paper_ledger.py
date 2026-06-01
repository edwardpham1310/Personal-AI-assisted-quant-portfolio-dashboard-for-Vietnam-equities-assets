"""Paper-trading ledger — cash + position bookkeeping with T+2 lazy settlement.

Reads/writes the paper_cash_ledger, paper_positions, and paper_accounts
tables through the SupabaseDB abstraction (so the in-memory fake works
the same as real PostgREST).

Lazy settlement model: pending rows in ``paper_cash_ledger`` flip from
PENDING → SETTLED on every call to ``settle_pending`` (invoked at the
top of every read-side route handler). Shares similarly: a BUY fill
adds to ``pending_quantity``; ``settle_pending`` moves matured pending
quantity into ``sellable_quantity`` based on ``filled_at + 2 BDays``.

T+2 skips weekends AND VN market holidays via
``services.vn_holidays.add_business_days`` (shared with
``services.order_preview`` so the two estimates always agree).
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

from core.security import AuthContext
from services.paper_execution import FillResult
from services.supabase_db import SupabaseDB
from services.vn_holidays import add_business_days as _add_business_days


def settlement_date_for(fill_at: datetime) -> date:
    return _add_business_days(fill_at.date(), 2)


# ── Cash helpers ────────────────────────────────────────────────────────────


async def get_current_cash(
    db: SupabaseDB, user: AuthContext, account_id: str
) -> float:
    rows = await db.select(
        "paper_accounts",
        where={"id": account_id, "user_id": user.user_id},
        user_jwt=user.raw_token,
    )
    if not rows:
        return 0.0
    return float(rows[0].get("current_cash") or 0.0)


async def get_pending_cash(
    db: SupabaseDB, user: AuthContext, account_id: str
) -> float:
    rows = await db.select(
        "paper_cash_ledger",
        where={"paper_account_id": account_id, "status": "PENDING"},
        user_jwt=user.raw_token,
    )
    return float(sum(float(r.get("amount") or 0.0) for r in rows))


async def settle_pending(
    db: SupabaseDB,
    user: AuthContext,
    account_id: str,
    *,
    now: datetime | None = None,
    audit_request: Any | None = None,
) -> int:
    """Flip matured PENDING ledger rows to SETTLED. Returns count flipped.

    Idempotent. Called at the top of every read-side route handler so
    the dashboard reflects the latest settlement state without a
    background job.

    Phase 2.7 review fix (CRITICAL):
    The sellable-quantity derivation previously aggregated *all
    historically settled* BUY fills for a symbol and assigned
    ``new_sellable = min(quantity, settled_now)``. After a
    sell-then-rebuy sequence this overstated sellable_quantity (it
    re-counted the original BUY's settled qty even though half had been
    sold), letting the user illegally sell unsettled rebuy shares.

    Correct derivation: track BOTH the settled BUY total and the
    cumulative SELL total per symbol, then
    ``new_sellable = max(0, settled_buy_total - sell_total)``,
    bounded by the current ``quantity``.
    """
    today = (now or datetime.now(UTC)).date()
    pending = await db.select(
        "paper_cash_ledger",
        where={"paper_account_id": account_id, "status": "PENDING"},
        user_jwt=user.raw_token,
    )
    flipped = 0
    for row in pending:
        sd = row.get("settled_date")
        if isinstance(sd, str):
            try:
                sd_date = date.fromisoformat(sd)
            except ValueError:
                continue
        elif isinstance(sd, date):
            sd_date = sd
        else:
            continue
        if sd_date <= today:
            await db.update(
                "paper_cash_ledger",
                {"status": "SETTLED"},
                where={"id": row["id"], "user_id": user.user_id},
                user_jwt=user.raw_token,
            )
            # Settled SELL_PROCEEDS_PENDING → current_cash += amount.
            if row.get("event_type") == "SELL_PROCEEDS_PENDING":
                current = await get_current_cash(db, user, account_id)
                await db.update(
                    "paper_accounts",
                    {"current_cash": current + float(row.get("amount") or 0.0)},
                    where={"id": account_id, "user_id": user.user_id},
                    user_jwt=user.raw_token,
                )
            flipped += 1

    # Settle BUY pending_quantity → sellable. Phase 2.7 review fix:
    # subtract SELL quantity per symbol so a sell-then-rebuy doesn't
    # double-count the first batch.
    fills = await db.select(
        "paper_fills",
        where={"paper_account_id": account_id},
        user_jwt=user.raw_token,
    )
    buy_settled_by_symbol: dict[str, int] = {}
    sells_by_symbol: dict[str, int] = {}
    for f in fills:
        sym = f["symbol"]
        qty = int(f.get("quantity") or 0)
        side = f.get("side")
        if side == "SELL":
            sells_by_symbol[sym] = sells_by_symbol.get(sym, 0) + qty
            continue
        filled_at_raw = f.get("filled_at")
        if isinstance(filled_at_raw, str):
            try:
                filled_at_dt = datetime.fromisoformat(
                    filled_at_raw.replace("Z", "+00:00")
                )
            except ValueError:
                continue
        elif isinstance(filled_at_raw, datetime):
            filled_at_dt = filled_at_raw
        else:
            continue
        sdate = settlement_date_for(filled_at_dt)
        if sdate <= today:
            buy_settled_by_symbol[sym] = (
                buy_settled_by_symbol.get(sym, 0) + qty
            )

    settled_symbols = set(buy_settled_by_symbol) | set(sells_by_symbol)
    if settled_symbols:
        positions = await db.select(
            "paper_positions",
            where={"paper_account_id": account_id},
            user_jwt=user.raw_token,
        )
        for p in positions:
            if p["symbol"] not in settled_symbols:
                continue
            settled_buy = buy_settled_by_symbol.get(p["symbol"], 0)
            sells = sells_by_symbol.get(p["symbol"], 0)
            qty = int(p.get("quantity") or 0)
            # The settled-available-to-sell pool is the cumulative
            # settled BUY qty minus the cumulative SELL qty (sells
            # consume from the settled pool first). Bounded by current
            # quantity to avoid negative pending.
            settled_pool = max(0, settled_buy - sells)
            new_sellable = min(qty, settled_pool)
            new_pending = max(0, qty - new_sellable)
            if (
                new_sellable != int(p.get("sellable_quantity") or 0)
                or new_pending != int(p.get("pending_quantity") or 0)
            ):
                await db.update(
                    "paper_positions",
                    {
                        "sellable_quantity": new_sellable,
                        "pending_quantity": new_pending,
                    },
                    where={"id": p["id"], "user_id": user.user_id},
                    user_jwt=user.raw_token,
                )
                flipped += 1

    # Emit an audit row when anything actually moved (matched the
    # previously-dead ``PAPER_SETTLEMENT_APPLIED`` action). Best-effort.
    if flipped > 0:
        try:
            await db.insert(
                "paper_audit_logs",
                {
                    "user_id": user.user_id,
                    "paper_account_id": account_id,
                    "action": "PAPER_SETTLEMENT_APPLIED",
                    "metadata": {"rows_flipped": flipped},
                },
                user_jwt=user.raw_token,
            )
        except Exception:  # pragma: no cover - audit must never block
            pass

    return flipped


# ── Apply a fill ────────────────────────────────────────────────────────────


async def apply_fill(
    db: SupabaseDB,
    user: AuthContext,
    account_id: str,
    *,
    order_id: str,
    symbol: str,
    fill: FillResult,
) -> dict[str, Any]:
    """Persist the fill row, update cash + position rows, and ledger.

    Returns the persisted fill row dict.
    """
    sdate = settlement_date_for(fill.filled_at).isoformat()

    fill_row = await db.insert(
        "paper_fills",
        {
            "user_id": user.user_id,
            "paper_account_id": account_id,
            "paper_order_id": order_id,
            "symbol": symbol,
            "side": fill.side,
            "quantity": fill.quantity,
            "fill_price": fill.fill_price,
            "gross_value": fill.gross_value,
            "brokerage_fee": fill.brokerage_fee,
            "vat": fill.vat,
            "sell_tax": fill.sell_tax,
            "slippage": fill.slippage,
            "net_cash_impact": fill.net_cash_impact,
            "filled_at": fill.filled_at.isoformat(),
        },
        user_jwt=user.raw_token,
    )

    current_cash = await get_current_cash(db, user, account_id)

    if fill.side == "BUY":
        # Immediate cash debit + create/extend position with pending qty.
        # Phase 2.7 review fix: previously ``max(0, new_cash)`` was used
        # to clamp. The clamp masked overspend bugs (rounding edge or
        # TOCTOU race could let a BUY through, then silently zero the
        # account). The pre-check in ``paper_execution.simulate_fill``
        # is the right guard; if we ever overshoot, the DB CHECK
        # ``current_cash >= 0`` will surface it as a 502 — louder is
        # better than wrong.
        new_cash = current_cash + fill.net_cash_impact  # net_cash_impact < 0
        await db.update(
            "paper_accounts",
            {"current_cash": new_cash},
            where={"id": account_id, "user_id": user.user_id},
            user_jwt=user.raw_token,
        )
        await db.insert(
            "paper_cash_ledger",
            {
                "user_id": user.user_id,
                "paper_account_id": account_id,
                "event_type": "BUY_DEBIT",
                "amount": fill.net_cash_impact,
                "settled_date": fill.filled_at.date().isoformat(),
                "status": "SETTLED",
                "metadata": {"order_id": order_id, "symbol": symbol},
            },
            user_jwt=user.raw_token,
        )
        await _upsert_position_on_buy(db, user, account_id, symbol, fill)
    else:  # SELL
        # Reduce position quantity immediately. Proceeds go to pending cash.
        await _reduce_position_on_sell(db, user, account_id, symbol, fill)
        await db.insert(
            "paper_cash_ledger",
            {
                "user_id": user.user_id,
                "paper_account_id": account_id,
                "event_type": "SELL_PROCEEDS_PENDING",
                "amount": fill.net_cash_impact,  # positive
                "settled_date": sdate,
                "status": "PENDING",
                "metadata": {"order_id": order_id, "symbol": symbol},
            },
            user_jwt=user.raw_token,
        )

    return dict(fill_row)


async def _upsert_position_on_buy(
    db: SupabaseDB,
    user: AuthContext,
    account_id: str,
    symbol: str,
    fill: FillResult,
) -> None:
    rows = await db.select(
        "paper_positions",
        where={"paper_account_id": account_id, "symbol": symbol},
        user_jwt=user.raw_token,
    )
    if rows:
        p = rows[0]
        old_qty = int(p.get("quantity") or 0)
        old_avg = float(p.get("avg_cost") or 0.0)
        new_qty = old_qty + fill.quantity
        new_avg = (
            (old_avg * old_qty + fill.fill_price * fill.quantity) / new_qty
            if new_qty > 0
            else 0.0
        )
        await db.update(
            "paper_positions",
            {
                "quantity": new_qty,
                "avg_cost": new_avg,
                "pending_quantity": int(p.get("pending_quantity") or 0)
                + fill.quantity,
            },
            where={"id": p["id"]},
            user_jwt=user.raw_token,
        )
    else:
        await db.insert(
            "paper_positions",
            {
                "user_id": user.user_id,
                "paper_account_id": account_id,
                "symbol": symbol,
                "quantity": fill.quantity,
                "sellable_quantity": 0,
                "pending_quantity": fill.quantity,
                "avg_cost": fill.fill_price,
            },
            user_jwt=user.raw_token,
        )


async def _reduce_position_on_sell(
    db: SupabaseDB,
    user: AuthContext,
    account_id: str,
    symbol: str,
    fill: FillResult,
) -> None:
    rows = await db.select(
        "paper_positions",
        where={"paper_account_id": account_id, "symbol": symbol},
        user_jwt=user.raw_token,
    )
    if not rows:
        return
    p = rows[0]
    new_qty = max(0, int(p.get("quantity") or 0) - fill.quantity)
    new_sellable = max(
        0, int(p.get("sellable_quantity") or 0) - fill.quantity
    )
    await db.update(
        "paper_positions",
        {"quantity": new_qty, "sellable_quantity": new_sellable},
        where={"id": p["id"]},
        user_jwt=user.raw_token,
    )
