"""Pure-Python Vietnam-equity order preview calculator.

This module computes the cost / proceeds / warnings / rejection reasons
for a hypothetical buy or sell, given:

* A live ``Quote`` snapshot (ceiling/floor/reference if available).
* A ``Security`` (lot_size, status).
* Optional ``avg_value_20d`` for liquidity checks.
* The user's ``CashBalance`` for BUY affordability.
* The user's ``StockPosition`` for SELL sellability.

It does NOT submit anything. The output is a pure calculation result.

Fee model (matches the rest of the codebase):
    brokerage_rate = 0.0015   (15 bps SSI all-in)
    vat_rate       = 0.10     (10% VAT on brokerage commission)
    sell_tax_rate  = 0.001    (0.1% capital-gains, sell only)
    slippage_rate  = 0.0010   (10 bps modelled slippage)

These rates intentionally match
``services/recommendation_engine.BROKERAGE_RATE/SLIPPAGE_RATE`` so the
preview agrees with the recommendation backtest.

The settlement T+2 estimate is computed naively (add 2 business days,
skipping weekends). Vietnamese holidays are *not* modelled — this is a
research-only estimate.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Literal

from schemas.market import Quote, Security
from schemas.trading import (
    CashBalance,
    OrderPreviewRequest,
    OrderPreviewResult,
    StockPosition,
    ValidationStatus,
)


# ── Vietnam equity fee constants ───────────────────────────────────────────


BROKERAGE_RATE = 0.0015      # 15 bps
VAT_RATE = 0.10              # 10% VAT on brokerage
SELL_TAX_RATE = 0.001        # 0.1% capital-gains, sell side only
SLIPPAGE_RATE = 0.0010       # 10 bps modelled slippage
DEFAULT_LOT_SIZE = 100       # HOSE default; HNX is 100 too in practice

# Liquidity ceiling: an order shouldn't exceed N% of 20d ADV.
MAX_ORDER_PCT_OF_ADV = 0.05   # 5% of average daily traded value


@dataclass(frozen=True)
class PreviewInputs:
    """Bundle of upstream data the calculator consumes."""

    request: OrderPreviewRequest
    quote: Quote | None
    security: Security | None
    cash: CashBalance | None
    position: StockPosition | None
    avg_value_20d: float | None = None


def _add_business_days(start: date, n: int) -> date:
    """T+N skipping Sat/Sun AND VN market holidays.

    Delegates to ``services.vn_holidays.add_business_days`` so the
    settlement-date estimate aligns with the paper_ledger lazy
    settlement clock.
    """
    from services.vn_holidays import add_business_days

    return add_business_days(start, n)


def _round_vnd(x: float) -> float:
    """Round to whole VND (no fractional dong)."""
    return float(round(x))


def _worst_status(
    cur: ValidationStatus, new: ValidationStatus
) -> ValidationStatus:
    """REJECTED dominates WARN dominates VALID."""
    order = {"VALID": 0, "WARN": 1, "REJECTED": 2}
    return cur if order[cur] >= order[new] else new


def calculate_preview(inputs: PreviewInputs) -> OrderPreviewResult:
    """Compute a preview result. Pure function — no I/O, no side effects.

    Validation rules:
    * Lot size (and no fractional shares).
    * Ceiling / floor band if the quote carries them.
    * Liquidity (order value vs 20d ADV).
    * BUY: total cash required <= buying power.
    * SELL: quantity <= sellable shares.
    * Market status: only ``ACTIVE`` securities are tradable.
    * Order type sanity: ``LIMIT`` requires a positive limit_price.
    """
    req = inputs.request
    warnings: list[str] = []
    rejections: list[str] = []
    status: ValidationStatus = "VALID"

    side: Literal["BUY", "SELL"] = req.side
    quantity = req.quantity
    price = float(req.limit_price)

    # ── 1. Lot size + integer shares ──────────────────────────────────
    lot = (inputs.security.lot_size or DEFAULT_LOT_SIZE) if inputs.security else DEFAULT_LOT_SIZE
    if lot <= 0:
        lot = DEFAULT_LOT_SIZE
    if quantity <= 0:
        rejections.append("QUANTITY_NON_POSITIVE")
        status = _worst_status(status, "REJECTED")
    elif quantity % lot != 0:
        rejections.append(f"LOT_SIZE_VIOLATION: quantity must be a multiple of {lot}")
        status = _worst_status(status, "REJECTED")

    # ── 2. Symbol / market status ─────────────────────────────────────
    if inputs.security is not None and inputs.security.status not in (None, "ACTIVE"):
        rejections.append(f"SYMBOL_NOT_TRADABLE: status={inputs.security.status}")
        status = _worst_status(status, "REJECTED")

    # ── 3. Quote freshness + ceiling/floor band ───────────────────────
    if inputs.quote is None:
        warnings.append("NO_LIVE_QUOTE: preview uses limit_price only")
    else:
        ceil_p = inputs.quote.ceiling_price
        floor_p = inputs.quote.floor_price
        if ceil_p is not None and price > ceil_p:
            rejections.append(
                f"PRICE_ABOVE_CEILING: limit={price} ceiling={ceil_p}"
            )
            status = _worst_status(status, "REJECTED")
        if floor_p is not None and price < floor_p:
            rejections.append(
                f"PRICE_BELOW_FLOOR: limit={price} floor={floor_p}"
            )
            status = _worst_status(status, "REJECTED")

    # ── 4. Liquidity vs 20d ADV ───────────────────────────────────────
    gross_value = price * quantity
    if inputs.avg_value_20d is not None and inputs.avg_value_20d > 0:
        adv_cap = inputs.avg_value_20d * MAX_ORDER_PCT_OF_ADV
        if gross_value > adv_cap:
            warnings.append(
                f"ORDER_EXCEEDS_5PCT_ADV: order={gross_value:.0f} cap={adv_cap:.0f}"
            )
            status = _worst_status(status, "WARN")

    # ── 5. Fee / tax / slippage math ──────────────────────────────────
    brokerage = gross_value * BROKERAGE_RATE
    vat = brokerage * VAT_RATE
    slippage = gross_value * SLIPPAGE_RATE
    sell_tax = gross_value * SELL_TAX_RATE if side == "SELL" else 0.0

    total_cash_required: float | None = None
    net_sell_proceeds: float | None = None

    if side == "BUY":
        total_cash_required = gross_value + brokerage + vat + slippage
        # Cash check.
        if inputs.cash is not None:
            if total_cash_required > inputs.cash.buying_power:
                shortfall = total_cash_required - inputs.cash.buying_power
                # Cash advance warning if pending cash would cover most of it.
                if (
                    inputs.cash.pending_cash > 0
                    and shortfall <= inputs.cash.pending_cash
                ):
                    warnings.append(
                        "CASH_ADVANCE_REQUIRED: pending sell proceeds could "
                        "cover the shortfall but a cash-advance fee applies"
                    )
                    status = _worst_status(status, "WARN")
                else:
                    rejections.append(
                        f"INSUFFICIENT_CASH: required={total_cash_required:.0f} "
                        f"available={inputs.cash.buying_power:.0f}"
                    )
                    status = _worst_status(status, "REJECTED")
        else:
            warnings.append("NO_CASH_SNAPSHOT: cannot verify buying power")
            status = _worst_status(status, "WARN")

    else:  # SELL
        net_sell_proceeds = gross_value - brokerage - vat - sell_tax - slippage
        if inputs.position is None:
            rejections.append("NO_POSITION: account does not hold this symbol")
            status = _worst_status(status, "REJECTED")
        elif quantity > inputs.position.sellable_quantity:
            rejections.append(
                f"INSUFFICIENT_SHARES: requested={quantity} "
                f"sellable={inputs.position.sellable_quantity}"
            )
            status = _worst_status(status, "REJECTED")
        elif (
            inputs.position.pending_quantity > 0
            and quantity
            > inputs.position.sellable_quantity - inputs.position.pending_quantity
        ):
            warnings.append(
                "PARTIALLY_PENDING: some held shares are still settling"
            )
            status = _worst_status(status, "WARN")
        warnings.append("T+2_SETTLEMENT: sell proceeds settle on T+2")
        # T+2 is informational but visible in the UI as a yellow notice.
        status = _worst_status(status, "WARN")

    # ── 6. T+2 settlement date (naive — weekend skip only) ────────────
    today = datetime.now(timezone.utc).date()
    settlement = _add_business_days(today, 2)

    return OrderPreviewResult(
        symbol=req.symbol.upper(),
        side=side,
        quantity=quantity,
        order_type=req.order_type,
        limit_price=price,
        estimated_value=_round_vnd(gross_value),
        estimated_fees=_round_vnd(brokerage),
        estimated_tax=_round_vnd(sell_tax),
        estimated_vat=_round_vnd(vat),
        estimated_slippage=_round_vnd(slippage),
        total_cash_required=(
            _round_vnd(total_cash_required) if total_cash_required is not None else None
        ),
        net_sell_proceeds=(
            _round_vnd(net_sell_proceeds) if net_sell_proceeds is not None else None
        ),
        settlement_date=settlement.isoformat(),
        validation_status=status,
        warnings=warnings,
        rejection_reasons=rejections,
        # Phase 2.5: ALWAYS false at API surface. Read by the UI.
        is_live_order_submission_enabled=False,
    )
