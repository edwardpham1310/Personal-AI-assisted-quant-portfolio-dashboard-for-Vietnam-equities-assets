"""Assets/PnL DTOs — Phase 1 (recommend-only, manual portfolio)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Exchange = Literal["HOSE", "HNX", "UPCOM"]
TradeSide = Literal["BUY", "SELL"]
CostPeriod = Literal["MTD", "YTD", "ALL"]


class CashBalance(BaseModel):
    """Vietnam-broker style cash buckets for a single account."""

    account_id: str
    settled_cash: float = 0.0
    pending_cash: float = 0.0
    advanced_cash: float = 0.0
    cash_advance_liability: float = 0.0
    withdrawable_cash: float = 0.0
    currency: str = "VND"
    as_of: str | None = None


class AssetsSummary(BaseModel):
    """Cash + equity rollup for the dashboard assets card."""

    account_id: str | None = None
    cash: CashBalance
    stock_market_value: float = 0.0
    total_equity: float = 0.0
    available_buying_power: float = 0.0
    currency: str = "VND"
    warnings: list[str] = Field(default_factory=list)
    disclaimer: str = "Research only — not financial advice. No orders placed."


class PnlBreakdown(BaseModel):
    """Top-level realized / unrealized rollup."""

    amount: float = 0.0
    cost_basis: float = 0.0
    return_pct: float | None = None


class PnlBySymbol(BaseModel):
    symbol: str
    realized: float = 0.0
    unrealized: float = 0.0
    cost_basis: float = 0.0


class CashMovement(BaseModel):
    """One trade-driven cash flow (signed). Deposits/withdrawals are not
    tracked — there is no external cash ledger for the manual portfolio."""

    date: str  # trade_date (YYYY-MM-DD)
    settlement_date: str | None = None
    symbol: str
    side: TradeSide
    gross: float = 0.0  # price * quantity
    fees: float = 0.0  # brokerage + vat + sell tax + advance + slippage
    amount: float = 0.0  # signed net cash impact: − on BUY, + on SELL


class CashMovementResponse(BaseModel):
    movements: list[CashMovement] = Field(default_factory=list)
    net_cash_flow: float = 0.0
    as_of: str | None = None
    note: str = "Trade-driven cash flows only — deposits/withdrawals are not tracked."
    disclaimer: str = "Research only — not financial advice. No orders placed."


class SettlementAlert(BaseModel):
    """A pending T+2 settlement derived from a trade's ``settlement_date``."""

    settlement_date: str
    symbol: str
    side: TradeSide
    kind: str  # "CASH_IN" (sell proceeds) | "SHARES_IN" (bought shares)
    quantity: int = 0
    amount: float | None = None  # settling cash for sells; None for buys
    days_until: int = 0


class SettlementResponse(BaseModel):
    alerts: list[SettlementAlert] = Field(default_factory=list)
    pending_count: int = 0
    pending_cash: float = 0.0  # authoritative aggregate from cash_balances
    as_of: str | None = None
    disclaimer: str = "T+2 settlement view. Research only — not financial advice."


class PnlBucket(BaseModel):
    """One ordered contribution bar in the PnL waterfall."""

    bucket: str
    value: float = 0.0


class PnlWaterfall(BaseModel):
    """Ordered PnL contribution series: Realized → Unrealized → Costs → Net.

    ``Realized`` is gross of fees (price-vs-avg-cost); ``Costs`` is the negated
    historical trade-fee total — the two are disjoint, so ``Net`` (their
    arithmetic sum) does not double-count. ``Costs`` covers realized trade
    costs only, not projected exit costs on open positions (Unrealized stays
    gross), so ``Net`` is not a liquidation value. Empty ``buckets`` is the
    honest-empty shape when there is no account / no trades and positions.
    """

    buckets: list[PnlBucket] = Field(default_factory=list)
    as_of: str | None = None
    disclaimer: str = "Research only — not financial advice. No orders placed."


class CostBreakdown(BaseModel):
    """Aggregated cost ledger for a period (MTD / YTD / ALL)."""

    period: CostPeriod = "ALL"
    brokerage_fee: float = 0.0
    vat: float = 0.0
    sell_tax: float = 0.0
    cash_advance_fee: float = 0.0
    slippage_estimate: float = 0.0
    total: float = 0.0
    trade_count: int = 0


class TradeTransactionCreate(BaseModel):
    """Body for recording a single manual trade — Phase 1 does not place orders."""

    symbol: str = Field(min_length=1, max_length=20)
    exchange: Exchange = "HOSE"
    side: TradeSide
    quantity: int = Field(gt=0)
    price: float = Field(ge=0)
    trade_date: str  # ISO date (YYYY-MM-DD)
    settlement_date: str | None = None
    brokerage_fee: float = 0.0
    vat: float = 0.0
    sell_tax: float = 0.0
    cash_advance_fee: float = 0.0
    slippage_estimate: float = 0.0
    note: str | None = Field(default=None, max_length=400)


class TradeTransaction(BaseModel):
    id: str
    account_id: str
    symbol: str
    exchange: Exchange
    side: TradeSide
    quantity: int
    price: float
    trade_date: str
    settlement_date: str | None = None
    brokerage_fee: float = 0.0
    vat: float = 0.0
    sell_tax: float = 0.0
    cash_advance_fee: float = 0.0
    slippage_estimate: float = 0.0
    note: str | None = None
    created_at: str | None = None
