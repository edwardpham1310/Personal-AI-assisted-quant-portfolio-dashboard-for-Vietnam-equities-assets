"""Phase 2.6 Auto-trade safety-foundation DTOs.

This module defines the schemas for the mode-state machine, risk-limit
configuration, audit actions, and re-auth challenge — **but no
order-submission schema** (Phase 2.6 does not execute trades).

The mode literal is intentionally explicit (no implicit fallback). The
``LIVE_AUTO`` mode is a request-only state from the client perspective;
even when stored, execution stays gated by environment flags.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

# ── Mode + audit literals ───────────────────────────────────────────────────


AutoTradeMode = Literal[
    "OFF",
    "PAPER_ONLY",
    "LIVE_MANUAL_CONFIRM",
    "LIVE_AUTO",
]

AutoTradeAuditAction = Literal[
    "AUTO_TRADE_SETTINGS_VIEWED",
    "AUTO_TRADE_SETTINGS_UPDATED",
    "AUTO_TRADE_ENABLE_PAPER",
    "AUTO_TRADE_ENABLE_MANUAL_CONFIRM_REQUESTED",
    "AUTO_TRADE_ENABLE_LIVE_AUTO_REQUESTED",
    "AUTO_TRADE_LIVE_AUTO_CONFIRMED",
    "AUTO_TRADE_DISABLED",
    "AUTO_TRADE_EMERGENCY_STOP",
    "AUTO_TRADE_REAUTH_FAILED",
    "AUTO_TRADE_REAUTH_SUCCESS",
    # Audit-of-audit: reading the audit log itself leaves a row so a
    # forensics investigator can answer "who saw what when".
    "AUTO_TRADE_AUDIT_VIEWED",
    # ── Phase 2.9 guarded auto trading engine ──
    "AUTO_TRADE_RUN_STARTED",
    "AUTO_TRADE_RUN_STOPPED",
    "AUTO_TRADE_RUN_PAUSED",
    "AUTO_TRADE_RUN_EMERGENCY_STOPPED",
    "AUTO_TRADE_RUN_FAILED",
    "AUTO_TRADE_DECISION_MADE",
    "AUTO_TRADE_DECISION_SKIPPED",
    "AUTO_TRADE_ORDER_PLACED_PAPER",
    "AUTO_TRADE_ORDER_PLACED_MANUAL_CONFIRM",
    "AUTO_TRADE_ORDER_PLACED_LIVE_DRY_RUN",
    "AUTO_TRADE_ORDER_PLACED_LIVE",
    "AUTO_TRADE_RISK_REJECTED",
    "AUTO_TRADE_WORKER_TICK",
    "AUTO_TRADE_WORKER_TICK_BLOCKED",
]


# ── Settings (the user's risk-limit configuration) ──────────────────────────


class AutoTradeSettings(BaseModel):
    """A single row in ``auto_trade_settings``, scoped to (user, account)."""

    id: str | None = None
    user_id: str
    account_id: str
    mode: AutoTradeMode = "OFF"
    enabled: bool = False

    # Risk limits — all default to 0 / None so a fresh row is forced
    # through the limit form before LIVE_* can be enabled.
    max_capital_vnd: float = Field(default=0, ge=0)
    max_order_value_vnd: float = Field(default=0, ge=0)
    max_orders_per_day: int = Field(default=0, ge=0)
    max_daily_loss_vnd: float = Field(default=0, ge=0)
    max_position_weight: float = Field(default=0, ge=0, le=1)
    max_sector_weight: float = Field(default=0, ge=0, le=1)

    allowed_strategies: list[str] = Field(default_factory=list)
    allowed_symbols: list[str] = Field(default_factory=list)
    allowed_watchlists: list[str] = Field(default_factory=list)

    require_manual_confirm: bool = True
    require_reauth: bool = True
    last_reauth_at: datetime | None = None
    risk_acknowledged_at: datetime | None = None

    created_at: datetime | None = None
    updated_at: datetime | None = None


class AutoTradeSettingsUpdate(BaseModel):
    """PUT /auto-trade/settings — partial update of risk limits + allowed
    lists. Does NOT include ``mode`` — mode transitions go through their
    dedicated endpoints."""

    max_capital_vnd: float | None = Field(default=None, ge=0)
    max_order_value_vnd: float | None = Field(default=None, ge=0)
    max_orders_per_day: int | None = Field(default=None, ge=0)
    max_daily_loss_vnd: float | None = Field(default=None, ge=0)
    max_position_weight: float | None = Field(default=None, ge=0, le=1)
    max_sector_weight: float | None = Field(default=None, ge=0, le=1)
    allowed_strategies: list[str] | None = None
    allowed_symbols: list[str] | None = None
    allowed_watchlists: list[str] | None = None
    require_manual_confirm: bool | None = None
    require_reauth: bool | None = None

    @field_validator("allowed_symbols")
    @classmethod
    def _upper_symbols(cls, v: list[str] | None) -> list[str] | None:
        if v is None:
            return None
        return [s.upper() for s in v if s.strip()]


# ── State (the running / emergency-stopped state) ───────────────────────────


class AutoTradeState(BaseModel):
    """A single row in ``auto_trade_state``, scoped to (user, account)."""

    id: str | None = None
    user_id: str
    account_id: str
    mode: AutoTradeMode = "OFF"
    is_running: bool = False
    last_started_at: datetime | None = None
    last_stopped_at: datetime | None = None
    emergency_stopped_at: datetime | None = None
    emergency_stop_reason: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


# ── Mode-transition requests ────────────────────────────────────────────────


class ModeTransitionRequest(BaseModel):
    """Body for enable-paper / enable-manual-confirm / disable.

    For LIVE_AUTO use the two-step Request → Confirm flow below.
    """

    account_id: str = Field(min_length=1, max_length=64)


class LiveAutoEnableConfirm(ModeTransitionRequest):
    """Body for confirm-live-auto-enable. The user must explicitly
    acknowledge the risk warning by setting ``risk_acknowledged=True``."""

    risk_acknowledged: bool


class EmergencyStopRequest(ModeTransitionRequest):
    """Body for emergency-stop. ``reason`` is free text for the audit log."""

    reason: str = Field(default="user_initiated", max_length=200)


# ── Mode-transition responses ───────────────────────────────────────────────


ValidationStatus = Literal["VALID", "REJECTED"]


class ModeTransitionResult(BaseModel):
    """Response envelope for every mode-change endpoint. Always carries
    the resulting mode + a structured rejection list so the UI can
    render a clear error banner."""

    account_id: str
    mode: AutoTradeMode
    validation_status: ValidationStatus
    rejection_reasons: list[str] = Field(default_factory=list)
    # Phase 2.6 invariant — ALWAYS false at API surface. The UI reads
    # this to keep the "Submit real order" affordance disabled.
    is_live_execution_enabled: bool = False
    last_reauth_at: datetime | None = None
    risk_acknowledged_at: datetime | None = None


class LiveAutoRequestResult(ModeTransitionResult):
    """Output of POST /auto-trade/request-live-auto-enable. Adds a
    boolean confirming the next step is the explicit confirm call."""

    next_step: Literal["CONFIRM_RISK_ACKNOWLEDGEMENT", "ABORT"]


# ── Audit log row ──────────────────────────────────────────────────────────


class AutoTradeAuditEntry(BaseModel):
    """One row from ``trading_audit_logs`` filtered to auto-trade actions."""

    id: str
    user_id: str
    account_id: str | None = None
    action: AutoTradeAuditAction
    metadata: dict = Field(default_factory=dict)
    created_at: datetime
