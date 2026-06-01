"""Phase 2.7 paper-trading DTOs.

Paper trading is **simulated only**. None of these schemas represent a
real broker order or position. The execution path:

  user request / recommendation
    → paper_execution.simulate_fill (pure math)
    → paper_ledger.apply_fill (cash + position bookkeeping)
    → paper_audit_logs row

Real SSI market data is used for the execution price in production. If
the provider is unavailable, the order is marked ``REJECTED`` with
``rejection_reason="DATA_UNAVAILABLE"`` — no silent fake-price fallback.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

Side = Literal["BUY", "SELL"]
OrderType = Literal["MARKET", "LIMIT"]
OrderStatus = Literal[
    "DRAFT",
    "SUBMITTED",
    "FILLED",
    "PARTIALLY_FILLED",
    "REJECTED",
    "CANCELLED",
]
SourceType = Literal["MANUAL", "RECOMMENDATION", "STRATEGY"]
CashEventType = Literal[
    "DEPOSIT",
    "BUY_DEBIT",
    "SELL_PROCEEDS_PENDING",
    "SELL_PROCEEDS_SETTLED",
    "FEE",
]
CashStatus = Literal["SETTLED", "PENDING"]

PaperAuditAction = Literal[
    "PAPER_ACCOUNT_CREATED",
    "PAPER_ORDER_FILLED",
    "PAPER_ORDER_REJECTED",
    "PAPER_ORDER_CANCELLED",
    # The cancel route also writes this when the order is non-cancellable
    # so the audit trail records the attempt (Phase 2.7 review fix).
    "PAPER_ORDER_CANCEL_REJECTED",
    "PAPER_RECOMMENDATION_RUN",
    "PAPER_STRATEGY_RUN_PLACEHOLDER",
    # Emitted by ``services.paper_ledger.settle_pending`` whenever it
    # flips one or more PENDING ledger rows or pending position quantity.
    "PAPER_SETTLEMENT_APPLIED",
]


# ── Accounts ────────────────────────────────────────────────────────────────


class PaperAccountCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    starting_cash: float = Field(default=100_000_000, ge=0, le=10_000_000_000)
    currency: str = Field(default="VND", min_length=3, max_length=3)


class PaperAccount(BaseModel):
    id: str
    user_id: str
    name: str
    starting_cash: float
    current_cash: float
    currency: str = "VND"
    created_at: datetime | None = None
    updated_at: datetime | None = None


# ── Orders + fills ──────────────────────────────────────────────────────────


class PaperOrderCreate(BaseModel):
    symbol: str = Field(min_length=1, max_length=20, pattern=r"^[A-Z0-9]+$")
    side: Side
    order_type: OrderType = "MARKET"
    quantity: int = Field(gt=0, le=10_000_000)
    limit_price: float | None = Field(default=None, gt=0, le=1_000_000_000)
    source_type: SourceType = "MANUAL"
    source_id: str | None = Field(default=None, max_length=64)


class PaperOrder(BaseModel):
    id: str
    user_id: str
    paper_account_id: str
    source_type: SourceType
    source_id: str | None = None
    symbol: str
    side: Side
    order_type: OrderType
    quantity: int
    limit_price: float | None = None
    status: OrderStatus
    rejection_reason: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class PaperFill(BaseModel):
    id: str
    user_id: str
    paper_account_id: str
    paper_order_id: str
    symbol: str
    side: Side
    quantity: int
    fill_price: float
    gross_value: float
    brokerage_fee: float
    vat: float
    sell_tax: float
    slippage: float
    net_cash_impact: float = Field(
        description="Signed amount applied to cash. Negative for BUY (cash out)."
    )
    filled_at: datetime


# ── Positions + ledger + equity ─────────────────────────────────────────────


class PaperPosition(BaseModel):
    id: str | None = None
    user_id: str
    paper_account_id: str
    symbol: str
    quantity: int = 0
    sellable_quantity: int = 0
    pending_quantity: int = 0
    avg_cost: float = 0
    market_price: float | None = None
    market_value: float | None = None
    unrealized_pnl: float | None = None
    updated_at: datetime | None = None


class PaperCashLedgerEntry(BaseModel):
    id: str
    user_id: str
    paper_account_id: str
    event_type: CashEventType
    amount: float = Field(description="Signed amount; positive = inflow.")
    settled_date: str
    status: CashStatus
    metadata: dict = Field(default_factory=dict)
    created_at: datetime


class PaperEquityPoint(BaseModel):
    id: str | None = None
    user_id: str
    paper_account_id: str
    timestamp: datetime
    cash: float
    pending_cash: float
    stock_value: float
    total_equity: float
    drawdown: float = 0


# ── Aggregator response (for the dashboard) ────────────────────────────────


class PaperAccountSummary(BaseModel):
    account: PaperAccount
    cash: float
    pending_cash: float
    stock_value: float
    total_equity: float
    realized_pnl: float
    unrealized_pnl: float
    drawdown: float
    open_orders: int
    positions: list[PaperPosition]
    data_status: Literal["FRESH", "DATA_UNAVAILABLE"] = "FRESH"


# ── Recommendation integration ─────────────────────────────────────────────


class RunRecommendationRequest(BaseModel):
    """Body for POST /paper/accounts/{id}/run-recommendation.

    The caller has previously inspected a recommendation; this request
    asks paper trading to simulate the suggested entry. Inputs come from
    the recommendation engine's structured result.
    """

    symbol: str = Field(min_length=1, max_length=20, pattern=r"^[A-Z0-9]+$")
    side: Side = "BUY"
    quantity: int = Field(gt=0, le=10_000_000)
    limit_price: float | None = Field(default=None, gt=0, le=1_000_000_000)
    recommendation_id: str | None = Field(default=None, max_length=64)


class PaperOrderResult(BaseModel):
    """Returned from POST /paper/accounts/{id}/orders and
    /run-recommendation. Carries the order + fill (if any).
    """

    order: PaperOrder
    fill: PaperFill | None = None
    rejection_reason: str | None = None
