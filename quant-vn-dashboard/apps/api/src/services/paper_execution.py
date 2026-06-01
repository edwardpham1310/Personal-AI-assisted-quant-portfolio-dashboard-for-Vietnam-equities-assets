"""Paper-trading fill calculator — pure functions.

Takes (side, qty, price, lot, ceiling/floor, cash, sellable shares) and
returns either a structured ``FillResult`` (the simulated fill) or a
``RejectionResult`` (with a stable reason code).

Fee constants are imported from ``services.order_preview`` so the paper
engine and the live preview agree on cost numbers — single source of
truth.

This module performs NO I/O. The orchestrator wires the market provider,
cash row, and position rows in; the result is consumed by
``services.paper_ledger`` which does the bookkeeping.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal

from services.order_preview import (
    BROKERAGE_RATE,
    DEFAULT_LOT_SIZE,
    SELL_TAX_RATE,
    SLIPPAGE_RATE,
    VAT_RATE,
    _round_vnd,
)

Side = Literal["BUY", "SELL"]


@dataclass(frozen=True)
class FillInputs:
    side: Side
    quantity: int
    fill_price: float
    lot_size: int = DEFAULT_LOT_SIZE
    ceiling_price: float | None = None
    floor_price: float | None = None
    buying_power: float = 0
    sellable_quantity: int = 0
    symbol_active: bool = True


@dataclass(frozen=True)
class FillResult:
    side: Side
    quantity: int
    fill_price: float
    gross_value: float
    brokerage_fee: float
    vat: float
    sell_tax: float
    slippage: float
    net_cash_impact: float  # signed: negative = cash out
    filled_at: datetime


@dataclass(frozen=True)
class RejectionResult:
    reason: str


def simulate_fill(inputs: FillInputs) -> FillResult | RejectionResult:
    """Return a fill or a rejection. Pure function — no I/O, no side effects.

    Rejection codes are stable strings the route layer surfaces verbatim
    on the persisted order row + audit log. Adding a new code is a
    minor schema bump.
    """
    if inputs.quantity <= 0:
        return RejectionResult("QUANTITY_NON_POSITIVE")

    lot = inputs.lot_size or DEFAULT_LOT_SIZE
    if inputs.quantity % lot != 0:
        return RejectionResult(f"LOT_SIZE_VIOLATION_lot{lot}")

    if not inputs.symbol_active:
        return RejectionResult("SYMBOL_NOT_TRADABLE")

    price = inputs.fill_price
    if price <= 0:
        return RejectionResult("FILL_PRICE_NON_POSITIVE")

    if inputs.ceiling_price is not None and price > inputs.ceiling_price:
        return RejectionResult("PRICE_ABOVE_CEILING")
    if inputs.floor_price is not None and price < inputs.floor_price:
        return RejectionResult("PRICE_BELOW_FLOOR")

    gross = price * inputs.quantity
    brokerage = gross * BROKERAGE_RATE
    vat = brokerage * VAT_RATE
    slippage = gross * SLIPPAGE_RATE
    sell_tax = gross * SELL_TAX_RATE if inputs.side == "SELL" else 0.0

    if inputs.side == "BUY":
        total_cash_required = gross + brokerage + vat + slippage
        if total_cash_required > inputs.buying_power:
            return RejectionResult("INSUFFICIENT_CASH")
        net = -total_cash_required
    else:
        if inputs.quantity > inputs.sellable_quantity:
            return RejectionResult("INSUFFICIENT_SHARES")
        net = gross - brokerage - vat - sell_tax - slippage

    return FillResult(
        side=inputs.side,
        quantity=inputs.quantity,
        fill_price=_round_vnd(price),
        gross_value=_round_vnd(gross),
        brokerage_fee=_round_vnd(brokerage),
        vat=_round_vnd(vat),
        sell_tax=_round_vnd(sell_tax),
        slippage=_round_vnd(slippage),
        net_cash_impact=_round_vnd(net),
        filled_at=datetime.now(timezone.utc),
    )
