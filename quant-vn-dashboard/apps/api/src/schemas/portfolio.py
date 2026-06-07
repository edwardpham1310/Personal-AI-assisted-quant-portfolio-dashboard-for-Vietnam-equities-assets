"""Manual portfolio DTOs."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Exchange = Literal["HOSE", "HNX", "UPCOM"]


class ManualAccountCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    broker: str = Field(default="SSI", max_length=32)
    currency: str = Field(default="VND", min_length=3, max_length=3)


class ManualAccount(BaseModel):
    id: str
    user_id: str
    name: str
    broker: str
    currency: str
    created_at: str | None = None
    updated_at: str | None = None


class ManualPositionCreate(BaseModel):
    account_id: str
    symbol: str = Field(min_length=1, max_length=20)
    exchange: Exchange = "HOSE"
    quantity: int = Field(gt=0)
    avg_cost: float = Field(ge=0)
    strategy_tag: str | None = Field(default=None, max_length=64)
    note: str | None = Field(default=None, max_length=400)


class ManualPositionUpdate(BaseModel):
    symbol: str | None = Field(default=None, min_length=1, max_length=20)
    exchange: Exchange | None = None
    quantity: int | None = Field(default=None, gt=0)
    avg_cost: float | None = Field(default=None, ge=0)
    strategy_tag: str | None = Field(default=None, max_length=64)
    note: str | None = Field(default=None, max_length=400)


class ManualPosition(BaseModel):
    id: str
    account_id: str
    symbol: str
    exchange: Exchange
    quantity: int
    avg_cost: float
    strategy_tag: str | None = None
    note: str | None = None
    sellable_quantity: int | None = 0
    pending_quantity: int | None = 0
    last_marked_at: str | None = None
    created_at: str | None = None
    updated_at: str | None = None


class ManualAccountWithPositions(ManualAccount):
    positions: list[ManualPosition] = []


class ManualPortfolioSnapshot(BaseModel):
    accounts: list[ManualAccountWithPositions] = []


# ── Phase 1 valuation DTOs ───────────────────────────────────────────────────


class PositionCreate(BaseModel):
    """POST /portfolio/positions — uses the user's default account."""

    symbol: str = Field(min_length=1, max_length=20)
    exchange: Exchange = "HOSE"
    quantity: int = Field(gt=0)
    avg_cost: float = Field(ge=0)
    strategy_tag: str | None = Field(default=None, max_length=64)
    note: str | None = Field(default=None, max_length=400)


class PositionUpdate(BaseModel):
    symbol: str | None = Field(default=None, min_length=1, max_length=20)
    exchange: Exchange | None = None
    quantity: int | None = Field(default=None, gt=0)
    avg_cost: float | None = Field(default=None, ge=0)
    strategy_tag: str | None = Field(default=None, max_length=64)
    note: str | None = Field(default=None, max_length=400)


class EnrichedPosition(BaseModel):
    """A manual position joined with the latest market price."""

    id: str
    account_id: str
    symbol: str
    exchange: Exchange
    quantity: int
    avg_cost: float
    strategy_tag: str | None = None
    note: str | None = None
    sellable_quantity: int = 0
    pending_quantity: int = 0
    last_marked_at: str | None = None
    created_at: str | None = None
    updated_at: str | None = None

    # Valuation overlay.
    market_price: float | None = None
    market_value: float | None = None
    unrealized_pnl: float | None = None
    unrealized_pnl_pct: float | None = None
    weight: float | None = None
    warnings: list[str] = Field(default_factory=list)


class PortfolioSummary(BaseModel):
    """Totals + grouping for the dashboard summary card."""

    total_market_value: float = 0.0
    total_cost_basis: float = 0.0
    total_unrealized_pnl: float = 0.0
    total_unrealized_pnl_pct: float | None = None
    position_count: int = 0
    last_marked_at: str | None = None
    by_strategy_tag: dict[str, float] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    disclaimer: str = "Research only — not financial advice. No orders placed."


class AllocationSlice(BaseModel):
    label: str  # strategy tag or symbol
    value: float  # market value in VND
    weight: float | None = None  # fraction of total (0..1); None when total==0


class AllocationResponse(BaseModel):
    """Allocation breakdown for the dashboard donut (point-in-time snapshot)."""

    by_strategy_tag: list[AllocationSlice] = Field(default_factory=list)
    by_symbol: list[AllocationSlice] = Field(default_factory=list)
    total_market_value: float = 0.0
    as_of: str | None = None
    warnings: list[str] = Field(default_factory=list)
    disclaimer: str = "Research only — market value at last poll. No orders placed."


class PositionDayPnl(BaseModel):
    symbol: str
    quantity: int
    prev_close: float | None = None  # = Quote.reference_price (session reference)
    current_price: float | None = None
    day_pnl: float | None = None
    day_pnl_pct: float | None = None


class TodayPnlResponse(BaseModel):
    """Intraday mark-to-market PnL vs the session reference price.

    TODO(today-pnl): ``prev_close`` is SSI's session reference price, already
    adjusted by the exchange on ex-div/split days — do NOT reuse for historical
    attribution. This is unrealized MTM, not net of sell tax (0.1%) / brokerage,
    and ignores T+2 settlement.
    """

    total_day_pnl: float = 0.0
    positions: list[PositionDayPnl] = Field(default_factory=list)
    as_of: str | None = None
    warnings: list[str] = Field(default_factory=list)
    disclaimer: str = (
        "Today MTM (unrealized, pre-cost). Not realized; not net of tax/fees. No orders placed."
    )


class EquityPoint(BaseModel):
    """One daily NAV point on the portfolio equity curve.

    ``ts`` is the snapshot trading day (YYYY-MM-DD, Asia/Ho_Chi_Minh);
    ``equity`` is total NAV at that mark. Matches the frontend ``EquityPoint``
    type. The curve is forward-only — it only contains days actually snapshotted.
    """

    ts: str
    equity: float = 0.0


class EquitySnapshotRunResult(BaseModel):
    """Outcome of POST /portfolio/snapshots/run (writer trigger)."""

    recorded: bool = False
    reason: str | None = None
    snapshot_date: str | None = None
    total_equity: float | None = None
    warnings: list[str] = Field(default_factory=list)


class RiskComponent(BaseModel):
    """One explainable contributor to the portfolio risk score."""

    key: str
    label: str
    available: bool = False
    score: float | None = None  # 0..100 risk subscore (higher = riskier)
    weight: float = 0.0  # blend weight (only counted when available)
    detail: str | None = None  # human explanation when available
    reason: str | None = None  # why unavailable


class RiskScoreResult(BaseModel):
    """Read-only, explainable portfolio risk score. Partial-aware: the overall
    ``score`` is the weighted mean of the AVAILABLE components only, and
    ``None`` when nothing can be computed (e.g. no positions). Never fabricated.
    """

    score: float | None = None  # 0..100, None when no component is available
    band: str = "unavailable"  # low | moderate | elevated | high | unavailable
    components: list[RiskComponent] = Field(default_factory=list)
    available_count: int = 0
    total_count: int = 0
    as_of: str | None = None
    disclaimer: str = "Research only — not financial advice. No orders placed."

