"""Phase 2.9 Guarded auto-trading engine DTOs.

State machine for ``auto_trade_runs``:

    STARTED
      ├─→ RUNNING
      │     ├─→ PAUSED
      │     │     └─→ RUNNING
      │     │     └─→ STOPPED
      │     ├─→ STOPPED
      │     ├─→ EMERGENCY_STOPPED   (panic button — Phase 2.6 reuse)
      │     └─→ FAILED              (uncaught exception in engine)
      └─→ STOPPED                   (start → immediate stop, e.g. preflight fail)
      └─→ FAILED

Terminal: STOPPED, EMERGENCY_STOPPED, FAILED.

The engine processes a "tick" — a unit of work that evaluates ONE or
more candidate symbols, applies risk, dispatches to the user's mode
(PAPER_ONLY / LIVE_MANUAL_CONFIRM / LIVE_AUTO), and records decisions.
Ticks are HTTP-triggered (no background daemon in Phase 2.9). The
``POST /auto-trade/worker/tick`` endpoint is the single entry point.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from schemas.auto_trade import AutoTradeMode

RunStatus = Literal[
    "STARTED",
    "RUNNING",
    "PAUSED",
    "STOPPED",
    "EMERGENCY_STOPPED",
    "FAILED",
]

DecisionAction = Literal[
    # Reco signal codes (used when the engine consumes a recommendation
    # row directly — Phase 2.9 candidates may carry these).
    "BUY_CANDIDATE",
    "WATCH",
    "HOLD",
    "AVOID",
    "REJECTED",
    # Order side — set when the engine acts on an explicit (symbol, side)
    # candidate (most common usage in Phase 2.9 worker ticks).
    "BUY",
    "SELL",
]

DecisionOutcome = Literal[
    # Engine outcomes — what actually happened:
    "DISPATCHED_PAPER",
    "DISPATCHED_MANUAL_CONFIRM",
    "DISPATCHED_LIVE_DRY_RUN",
    "DISPATCHED_LIVE",
    "SKIPPED_BY_RISK",
    "SKIPPED_NOT_ALLOWED",
    "SKIPPED_COOLDOWN",
    "SKIPPED_KILL_SWITCH",
    "SKIPPED_MARKET_CLOSED",
    "SKIPPED_DATA_STALE",
    "SKIPPED_NOT_RECOMMENDED",
]

OrderMode = Literal[
    "PAPER", "MANUAL_CONFIRM", "LIVE_DRY_RUN", "LIVE",
]


# ── Runs ────────────────────────────────────────────────────────────────────


class RunStartRequest(BaseModel):
    """Body for POST /auto-trade/runs/start."""

    account_id: str = Field(min_length=1, max_length=64)
    strategy_id: str = Field(default="default", max_length=64)
    # Optional caller-provided run metadata.
    metadata: dict = Field(default_factory=dict)


class AutoTradeRun(BaseModel):
    id: str
    user_id: str
    account_id: str
    mode: AutoTradeMode
    strategy_id: str
    status: RunStatus
    started_at: datetime | None = None
    stopped_at: datetime | None = None
    metadata: dict = Field(default_factory=dict)


# ── Decisions ──────────────────────────────────────────────────────────────


class AutoTradeDecision(BaseModel):
    id: str
    user_id: str
    account_id: str
    run_id: str
    symbol: str
    recommendation_id: str | None = None
    action: DecisionAction
    decision: DecisionOutcome
    reason: dict = Field(default_factory=dict)
    risk_snapshot: dict = Field(default_factory=dict)
    created_at: datetime


# ── Orders (the linkage row to paper / live-order-intent) ─────────────────


class AutoTradeOrder(BaseModel):
    id: str
    user_id: str
    account_id: str
    run_id: str
    decision_id: str
    live_order_intent_id: str | None = None
    paper_order_id: str | None = None
    mode: OrderMode
    status: str
    created_at: datetime


# ── Daily risk counters ────────────────────────────────────────────────────


class AutoTradeRiskCounter(BaseModel):
    id: str
    user_id: str
    account_id: str
    trading_date: str  # ISO date
    orders_count: int = 0
    gross_order_value: float = 0
    realized_loss: float = 0
    unrealized_loss: float = 0
    daily_loss: float = 0
    updated_at: datetime


# ── Worker tick request + response ─────────────────────────────────────────


class WorkerTickRequest(BaseModel):
    """Body for POST /auto-trade/worker/tick.

    The caller supplies the candidate symbols (and optionally explicit
    recommendation actions) for THIS tick. The engine evaluates each,
    applies risk + cooldown, dispatches based on the user's mode.

    Phase 2.9 does NOT include a background daemon — an external
    scheduler (cron, k8s CronJob, etc.) is the trigger. Authentication
    on the route is enforced separately.
    """

    run_id: str = Field(min_length=1, max_length=64)
    candidates: list[dict] = Field(
        default_factory=list,
        description=(
            "List of {symbol, action, recommendation_id?, "
            "quantity, limit_price?} entries. Up to "
            "AUTO_TRADE_MAX_DECISIONS_PER_TICK per call."
        ),
    )


class TickResult(BaseModel):
    run_id: str
    decisions: list[AutoTradeDecision] = Field(default_factory=list)
    orders: list[AutoTradeOrder] = Field(default_factory=list)
    skipped_count: int = 0
    dispatched_count: int = 0
    is_dry_run: bool = True
    gate_status: dict = Field(default_factory=dict)


# ── Risk validation result (returned from auto_trade_risk) ────────────────


ValidationStatus = Literal["VALID", "WARN", "REJECTED"]


class RiskValidationResult(BaseModel):
    status: ValidationStatus
    reasons: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    snapshot: dict = Field(default_factory=dict)
