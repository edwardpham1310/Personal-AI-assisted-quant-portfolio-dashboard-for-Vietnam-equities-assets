"""Phase 2.5 SSI Trading read-only + order-preview DTOs.

This module ONLY contains schemas for:
* read-only broker views (cash, positions, max-buy/sell, order book, history),
* the order-preview calculator,
* the audit log.

It does NOT contain a "submit order" schema. The forbidden routes
(POST /trading/new-order, /submit-order, /cancel-order) return 501 and
do not need a request body — adding one would prime someone to fill them in.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

Side = Literal["BUY", "SELL"]
OrderType = Literal["LIMIT", "MARKET", "ATO", "ATC", "MTL"]
ValidationStatus = Literal["VALID", "WARN", "REJECTED"]

# A trading account is a *broker* account (the user's SSI account), distinct
# from the *manual* portfolio account managed under /portfolio/.
TradingExchange = Literal["HOSE", "HNX", "UPCOM"]


# ── Broker account inventory ────────────────────────────────────────────────


class TradingAccount(BaseModel):
    """A broker (SSI) account registered for read-only access."""

    id: str
    user_id: str
    broker: str = "SSI"
    account_number_masked: str = Field(
        description="Last-4 form, e.g. '****1234'. Full number never returned."
    )
    account_alias: str | None = None
    read_only_enabled: bool = True
    trading_enabled: bool = False  # Phase 2.5 ALWAYS false at API surface
    created_at: datetime | None = None
    updated_at: datetime | None = None


class TradingAccountCreate(BaseModel):
    """POST /trading/accounts — register a broker account for read-only sync.

    The full account number is never persisted in plain text; the route
    layer reduces it to the last-4 masked form. Phase 2.5 never accepts
    a credential here — credentials live in env on the API host.
    """

    account_number: str = Field(
        min_length=4,
        max_length=24,
        description="Full account number; only last-4 is persisted (masked).",
    )
    account_alias: str | None = Field(default=None, max_length=80)
    broker: str = Field(default="SSI", max_length=32)


# ── Cash, positions, max-qty ────────────────────────────────────────────────


class CashBalance(BaseModel):
    account_id: str
    cash_balance: float = Field(ge=0, description="Total cash recorded by broker.")
    buying_power: float = Field(ge=0, description="Settled cash usable for new buys.")
    withdrawable_cash: float = Field(ge=0)
    pending_cash: float = Field(
        ge=0,
        description="Sell proceeds not yet settled (T+2 pending settlement).",
    )
    currency: str = "VND"
    as_of: datetime


class StockPosition(BaseModel):
    account_id: str
    symbol: str
    exchange: TradingExchange | None = None
    quantity: int = Field(ge=0)
    sellable_quantity: int = Field(
        ge=0, description="Settled and unencumbered shares available to sell."
    )
    pending_quantity: int = Field(
        ge=0, description="Bought T or T-1 shares still settling."
    )
    avg_cost: float = Field(ge=0)
    market_price: float | None = None
    market_value: float | None = None
    unrealized_pnl: float | None = None
    as_of: datetime


class SsiAccountSnapshot(BaseModel):
    """Read-only SSI account snapshot for the dashboard broker card.

    Aggregates ``status`` + ``cash`` + ``positions`` in one response. Real data
    appears only when the provider is a genuinely configured, read-only SSI
    connection (``connected=True``). In mock/dev or when SSI is unconfigured,
    ``connected=False`` and ``cash``/``positions`` are omitted — fabricated
    balances are NEVER surfaced. No order placement happens here.
    """

    connected: bool = False
    status_code: str
    mock: bool = False
    account_masked: str | None = None
    cash: CashBalance | None = None
    positions: list[StockPosition] = Field(default_factory=list)
    note: str | None = None
    disclaimer: str = "Read-only SSI account snapshot — no orders are placed."


class MaxBuyQuantity(BaseModel):
    account_id: str
    symbol: str
    price: float = Field(gt=0)
    max_quantity: int = Field(ge=0)
    buying_power: float = Field(ge=0)
    note: str | None = None
    as_of: datetime


class MaxSellQuantity(BaseModel):
    account_id: str
    symbol: str
    max_quantity: int = Field(ge=0)
    sellable_quantity: int = Field(ge=0)
    note: str | None = None
    as_of: datetime


# ── Order book + order history (read-only) ──────────────────────────────────


OrderStatus = Literal[
    "PENDING",
    "ACTIVE",
    "PARTIALLY_FILLED",
    "FILLED",
    "CANCELLED",
    "REJECTED",
    "EXPIRED",
    "UNKNOWN",
]


class OrderBookEntry(BaseModel):
    """An open / in-flight order. Read-only — Phase 2.5 cannot cancel/modify."""

    order_id: str
    account_id: str
    symbol: str
    side: Side
    order_type: OrderType
    quantity: int = Field(ge=0)
    filled_quantity: int = Field(ge=0)
    limit_price: float | None = None
    average_fill_price: float | None = None
    status: OrderStatus
    placed_at: datetime | None = None
    updated_at: datetime | None = None


class OrderHistoryEntry(OrderBookEntry):
    """A historical (closed) order."""

    closed_at: datetime | None = None
    realized_pnl: float | None = None


# ── Order preview (the headline Phase 2.5 deliverable) ──────────────────────


class OrderPreviewRequest(BaseModel):
    """Input to the preview calculator. Validated by FastAPI before reaching
    the service. The calculator never reaches a submission endpoint."""

    account_id: str = Field(min_length=1, max_length=64)
    # ``pattern`` rejects Unicode lookalikes, control chars, HTML
    # injection attempts, and whitespace. VN tickers are 1-12 uppercase
    # ASCII letters/digits in practice (e.g. ``FPT``, ``VN30F2412``).
    symbol: str = Field(min_length=1, max_length=20, pattern=r"^[A-Z0-9]+$")
    side: Side
    quantity: int = Field(gt=0, le=10_000_000)
    limit_price: float = Field(gt=0, le=10_000_000)
    order_type: OrderType = "LIMIT"


class OrderPreviewResult(BaseModel):
    """Calculator output — never sent to a broker."""

    symbol: str
    side: Side
    quantity: int
    order_type: OrderType
    limit_price: float
    estimated_value: float = Field(
        ge=0, description="Gross value: limit_price * quantity."
    )
    estimated_fees: float = Field(
        ge=0, description="Brokerage commission only (excludes VAT/tax)."
    )
    estimated_tax: float = Field(
        ge=0, description="Sell-side capital gains tax (0 for BUY)."
    )
    estimated_vat: float = Field(
        ge=0, description="VAT on brokerage commission."
    )
    estimated_slippage: float = Field(
        ge=0, description="Modelled slippage at the SLIPPAGE_RATE constant."
    )
    total_cash_required: float | None = Field(
        default=None,
        description="BUY only: limit*qty + fees + vat + slippage.",
    )
    net_sell_proceeds: float | None = Field(
        default=None,
        description="SELL only: limit*qty - fees - vat - sell_tax - slippage.",
    )
    settlement_date: str | None = Field(
        default=None,
        description="ISO date of T+2 settlement (read-only estimate).",
    )
    validation_status: ValidationStatus
    warnings: list[str] = Field(default_factory=list)
    rejection_reasons: list[str] = Field(default_factory=list)

    # Explicit kill-switch the UI reads. Always false in Phase 2.5.
    is_live_order_submission_enabled: bool = False


# ── Persisted preview row (audit / history) ─────────────────────────────────


class OrderPreviewRecord(BaseModel):
    """Stored copy of a generated preview — for audit + 'recent previews'."""

    id: str
    user_id: str
    account_id: str
    symbol: str
    side: Side
    order_type: OrderType
    quantity: int
    limit_price: float
    estimated_value: float
    estimated_fees: float
    estimated_tax: float
    estimated_vat: float
    estimated_slippage: float
    total_cash_required: float | None
    net_sell_proceeds: float | None
    validation_status: ValidationStatus
    warnings: list[str]
    rejection_reasons: list[str]
    created_at: datetime


# ── Trading provider status (system observability) ─────────────────────────


TradingProviderStatusCode = Literal[
    "CONNECTED",
    "CONFIG_MISSING",
    "AUTH_FAILED",
    "READ_ONLY",
    "ORDER_PLACEMENT_DISABLED",
    "ERROR",
    "NOT_IMPLEMENTED",
]


class TradingProviderStatus(BaseModel):
    """Observability for the trading provider — surfaced on /system/."""

    name: str
    mock: bool
    read_only: bool
    order_placement_enabled: bool
    status_code: TradingProviderStatusCode
    last_call_ts: datetime | None = None
    last_error_sanitized: str | None = None
    note: str | None = None
