"""Pure portfolio valuation helpers.

I/O lives in the route layer; everything here takes plain dicts / Pydantic
models in and returns Pydantic models out so it stays trivially unit-testable.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timezone
from typing import Any, Iterable
from zoneinfo import ZoneInfo

# Period anchors (MTD/YTD) follow the operator's wall clock in Vietnam, not
# UTC — otherwise a trade dated late evening Asia/Ho_Chi_Minh time can be
# bucketed into the previous month/year.
_ICT = ZoneInfo("Asia/Ho_Chi_Minh")

from schemas.assets import CostBreakdown, CostPeriod, PnlBreakdown, PnlBySymbol
from schemas.market import Quote
from schemas.portfolio import EnrichedPosition, PortfolioSummary


# ── Per-position enrichment ──────────────────────────────────────────────────


def enrich_position(
    position: dict[str, Any],
    market_price: float | None,
    *,
    weight: float | None = None,
    last_marked_at: str | None = None,
    extra_warnings: Iterable[str] | None = None,
) -> EnrichedPosition:
    """Decorate a raw manual_position row with valuation fields.

    weight is supplied by the caller because it's computed across the whole set.
    """
    quantity = int(position.get("quantity") or 0)
    avg_cost = float(position.get("avg_cost") or 0.0)
    cost_basis = quantity * avg_cost

    warnings: list[str] = list(extra_warnings or [])

    market_value: float | None
    unrealized_pnl: float | None
    unrealized_pct: float | None
    if market_price is None:
        market_value = None
        unrealized_pnl = None
        unrealized_pct = None
        warnings.append("quote_missing")
    else:
        market_value = quantity * market_price
        unrealized_pnl = market_value - cost_basis
        # Avoid div/0 — zero cost basis = pct is undefined, not infinity.
        unrealized_pct = (unrealized_pnl / cost_basis) if cost_basis > 0 else None

    return EnrichedPosition(
        id=str(position.get("id")),
        account_id=str(position.get("account_id")),
        symbol=str(position.get("symbol", "")).upper(),
        exchange=position.get("exchange") or "HOSE",
        quantity=quantity,
        avg_cost=avg_cost,
        strategy_tag=position.get("strategy_tag"),
        note=position.get("note"),
        sellable_quantity=int(position.get("sellable_quantity") or 0),
        pending_quantity=int(position.get("pending_quantity") or 0),
        last_marked_at=last_marked_at or position.get("last_marked_at"),
        created_at=position.get("created_at"),
        updated_at=position.get("updated_at"),
        market_price=market_price,
        market_value=market_value,
        unrealized_pnl=unrealized_pnl,
        unrealized_pnl_pct=unrealized_pct,
        weight=weight,
        warnings=warnings,
    )


# ── Aggregate summary ────────────────────────────────────────────────────────


def compute_summary(
    positions: list[dict[str, Any]],
    quotes: list[Quote | None],
) -> tuple[PortfolioSummary, list[EnrichedPosition]]:
    """Return (summary, enriched_positions). Caller decides what to surface.

    Quotes must align positionally with ``positions``.
    """
    if not positions:
        return PortfolioSummary(), []

    if len(quotes) != len(positions):
        raise ValueError("quotes length must match positions length")

    # First pass — compute market values to derive weights.
    raw_market_values: list[float | None] = []
    for pos, quote in zip(positions, quotes):
        if quote is None:
            raw_market_values.append(None)
        else:
            raw_market_values.append(int(pos.get("quantity") or 0) * float(quote.price))

    total_market_value = sum(v for v in raw_market_values if v is not None)

    enriched: list[EnrichedPosition] = []
    by_tag: dict[str, float] = defaultdict(float)
    total_cost_basis = 0.0
    aggregate_warnings: list[str] = []
    latest_ts: datetime | None = None

    for pos, quote, mv in zip(positions, quotes, raw_market_values):
        weight: float | None
        if mv is None or total_market_value <= 0:
            weight = None
        else:
            weight = mv / total_market_value

        last_marked: str | None = None
        if quote is not None:
            last_marked = quote.ts.isoformat() if isinstance(quote.ts, datetime) else str(quote.ts)
            if isinstance(quote.ts, datetime):
                ts_aware = quote.ts if quote.ts.tzinfo else quote.ts.replace(tzinfo=timezone.utc)
                if latest_ts is None or ts_aware > latest_ts:
                    latest_ts = ts_aware

        ep = enrich_position(
            pos,
            market_price=float(quote.price) if quote is not None else None,
            weight=weight,
            last_marked_at=last_marked,
        )
        enriched.append(ep)

        # Cost basis always counts (it's known regardless of price availability).
        total_cost_basis += ep.quantity * ep.avg_cost

        if mv is not None:
            tag = ep.strategy_tag or "untagged"
            by_tag[tag] += mv

        if "quote_missing" in ep.warnings and ep.symbol not in aggregate_warnings:
            aggregate_warnings.append(f"quote_missing:{ep.symbol}")

    total_unrealized = total_market_value - total_cost_basis
    total_pct: float | None
    if total_cost_basis > 0:
        total_pct = total_unrealized / total_cost_basis
    else:
        total_pct = None

    summary = PortfolioSummary(
        total_market_value=total_market_value,
        total_cost_basis=total_cost_basis,
        total_unrealized_pnl=total_unrealized,
        total_unrealized_pnl_pct=total_pct,
        position_count=len(positions),
        last_marked_at=latest_ts.isoformat() if latest_ts else None,
        by_strategy_tag=dict(by_tag),
        warnings=aggregate_warnings,
    )
    return summary, enriched


# ── Realized PnL via weighted-average cost ───────────────────────────────────


def realized_pnl_from_trades(
    trades: list[dict[str, Any]],
) -> dict[str, Any]:
    """Phase 1 realized-PnL model.

    Walk trades in chronological order. Maintain running (quantity, avg_cost)
    per (account_id, symbol). On BUY: weighted-average cost is updated. On
    SELL: realized += sell_qty * (sell_price - running_avg_cost), and qty
    decreases.

    Returns::

        {
          "total_realized": float,
          "by_symbol": {symbol: {"realized": float, "cost_basis_at_sell": float}}
        }
    """
    sorted_trades = sorted(
        trades,
        key=lambda t: (str(t.get("trade_date") or ""), str(t.get("created_at") or "")),
    )

    # Key is (account_id, symbol) so the same symbol in two accounts stays separate.
    running: dict[tuple[str, str], tuple[float, float]] = {}
    by_symbol: dict[str, dict[str, float]] = defaultdict(
        lambda: {"realized": 0.0, "cost_basis_at_sell": 0.0}
    )
    total_realized = 0.0

    for trade in sorted_trades:
        symbol = str(trade.get("symbol", "")).upper()
        account_id = str(trade.get("account_id") or "")
        side = str(trade.get("side") or "").upper()
        qty = float(trade.get("quantity") or 0)
        price = float(trade.get("price") or 0.0)

        if qty <= 0:
            continue

        key = (account_id, symbol)
        cur_qty, cur_avg = running.get(key, (0.0, 0.0))

        if side == "BUY":
            new_qty = cur_qty + qty
            # Weighted-average cost.
            if new_qty > 0:
                new_avg = ((cur_qty * cur_avg) + (qty * price)) / new_qty
            else:
                new_avg = 0.0
            running[key] = (new_qty, new_avg)
        elif side == "SELL":
            # Can't sell more than we hold in this simple model — clamp.
            sell_qty = min(qty, cur_qty) if cur_qty > 0 else qty
            realized = sell_qty * (price - cur_avg)
            cost_for_lot = sell_qty * cur_avg

            total_realized += realized
            by_symbol[symbol]["realized"] += realized
            by_symbol[symbol]["cost_basis_at_sell"] += cost_for_lot

            remaining = max(cur_qty - sell_qty, 0.0)
            # Avg cost survives a partial sell unchanged; zero out when flat.
            running[key] = (remaining, cur_avg if remaining > 0 else 0.0)

    return {
        "total_realized": total_realized,
        "by_symbol": {sym: dict(vals) for sym, vals in by_symbol.items()},
    }


# ── Costs ────────────────────────────────────────────────────────────────────


def _period_start(period: CostPeriod, today: date) -> date | None:
    if period == "MTD":
        return today.replace(day=1)
    if period == "YTD":
        return today.replace(month=1, day=1)
    return None  # ALL


def cost_breakdown(
    trades: list[dict[str, Any]],
    period: CostPeriod = "ALL",
    *,
    today: date | None = None,
) -> CostBreakdown:
    """Sum fee fields across trades, optionally filtered by period."""
    # MTD/YTD boundaries follow Asia/Ho_Chi_Minh local time. ``today`` can
    # still be overridden for deterministic tests.
    today = today or datetime.now(_ICT).date()
    start = _period_start(period, today)

    brokerage = vat = sell_tax = advance = slippage = 0.0
    count = 0
    for trade in trades:
        td = trade.get("trade_date")
        if isinstance(td, str):
            try:
                td_parsed = date.fromisoformat(td[:10])
            except ValueError:
                continue
        elif isinstance(td, date):
            td_parsed = td
        else:
            continue
        if start is not None and td_parsed < start:
            continue

        brokerage += float(trade.get("brokerage_fee") or 0.0)
        vat += float(trade.get("vat") or 0.0)
        sell_tax += float(trade.get("sell_tax") or 0.0)
        advance += float(trade.get("cash_advance_fee") or 0.0)
        slippage += float(trade.get("slippage_estimate") or 0.0)
        count += 1

    total = brokerage + vat + sell_tax + advance + slippage
    return CostBreakdown(
        period=period,
        brokerage_fee=brokerage,
        vat=vat,
        sell_tax=sell_tax,
        cash_advance_fee=advance,
        slippage_estimate=slippage,
        total=total,
        trade_count=count,
    )


# ── Pnl by symbol (for /assets/pnl) ──────────────────────────────────────────


def build_pnl_by_symbol(
    enriched: list[EnrichedPosition],
    realized: dict[str, Any],
) -> list[PnlBySymbol]:
    """Merge unrealized (per enriched position) with realized (per trade lot)."""
    rows: dict[str, PnlBySymbol] = {}
    for ep in enriched:
        rows[ep.symbol] = PnlBySymbol(
            symbol=ep.symbol,
            unrealized=float(ep.unrealized_pnl or 0.0),
            cost_basis=ep.quantity * ep.avg_cost,
        )

    for sym, vals in (realized.get("by_symbol") or {}).items():
        existing = rows.get(sym) or PnlBySymbol(symbol=sym)
        existing.realized = float(vals.get("realized", 0.0))
        # Use cost_basis_at_sell as a floor; if we still hold a position the
        # held cost basis already covers it.
        if existing.cost_basis == 0.0:
            existing.cost_basis = float(vals.get("cost_basis_at_sell", 0.0))
        rows[sym] = existing

    return sorted(rows.values(), key=lambda r: r.symbol)
