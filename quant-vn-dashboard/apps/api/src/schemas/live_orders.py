"""Phase 2.8 Manual-confirm live trading DTOs.

State machine for ``live_order_intents``:

    DRAFT
      └─→ PREVIEWED  (POST /preview)
            └─→ CONFIRM_REQUIRED  (POST /request-confirmation)
                  ├─→ CONFIRMED   (POST /confirm)
                  │     ├─→ SUBMITTED  (POST /submit — dry-run or live success)
                  │     ├─→ REJECTED   (any submit-time gate fails)
                  │     └─→ FAILED     (broker error after gate passes)
                  └─→ CANCELLED   (POST /cancel)
      └─→ CANCELLED  (cancel from any non-terminal state)

The orchestrator (services/live_orders.py) enforces this matrix.
Terminal states: SUBMITTED, REJECTED, CANCELLED, FAILED.

No status here represents a queued / in-flight / pending live order —
Phase 2.8 is synchronous from the user's perspective. A future Phase 3
may add async / partial-fill states.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

Side = Literal["BUY", "SELL"]
OrderType = Literal["LIMIT", "MARKET", "ATO", "ATC", "MTL"]
SourceType = Literal["MANUAL", "RECOMMENDATION", "PAPER_COPY", "STRATEGY"]

LiveOrderIntentStatus = Literal[
    "DRAFT",
    "PREVIEWED",
    "CONFIRM_REQUIRED",
    "CONFIRMED",
    "SUBMITTED",
    "REJECTED",
    "CANCELLED",
    "FAILED",
]

LiveOrderSubmissionStatus = Literal[
    "DRY_RUN_OK",
    "LIVE_OK",
    "REJECTED_BY_GATE",
    "BROKER_ERROR",
]

# Audit actions written to ``trading_audit_logs`` for this phase.
LiveOrderAuditAction = Literal[
    "LIVE_ORDER_INTENT_CREATED",
    "LIVE_ORDER_PREVIEWED",
    "LIVE_ORDER_CONFIRMATION_REQUESTED",
    "LIVE_ORDER_REAUTH_FAILED",
    "LIVE_ORDER_CONFIRMED",
    # Phase 2.8 review fix: distinct from SUBMIT_REJECTED so an auditor
    # filtering for submission-time rejections doesn't get polluted by
    # confirmation-step failures (risk-ack false, stale reauth at confirm).
    "LIVE_ORDER_CONFIRM_REJECTED",
    "LIVE_ORDER_SUBMIT_ATTEMPTED",
    "LIVE_ORDER_SUBMIT_REJECTED",
    "LIVE_ORDER_SUBMIT_DRY_RUN_OK",
    "LIVE_ORDER_SUBMIT_LIVE_OK",
    "LIVE_ORDER_SUBMIT_BROKER_ERROR",
    "LIVE_ORDER_CANCELLED",
]


# ── Intent CRUD ─────────────────────────────────────────────────────────────


class LiveOrderIntentCreate(BaseModel):
    account_id: str = Field(min_length=1, max_length=64)
    symbol: str = Field(min_length=1, max_length=20, pattern=r"^[A-Z0-9]+$")
    side: Side
    order_type: OrderType = "LIMIT"
    quantity: int = Field(gt=0, le=10_000_000)
    limit_price: float | None = Field(default=None, gt=0, le=1_000_000_000)
    source_type: SourceType = "MANUAL"
    source_id: str | None = Field(default=None, max_length=64)


class LiveOrderIntent(BaseModel):
    id: str
    user_id: str
    account_id: str
    source_type: SourceType
    source_id: str | None = None
    symbol: str
    side: Side
    order_type: OrderType
    quantity: int
    limit_price: float | None = None
    preview_id: str | None = None
    status: LiveOrderIntentStatus
    validation_snapshot: dict | None = None
    warnings: list[str] = Field(default_factory=list)
    rejection_reasons: list[str] = Field(default_factory=list)
    created_at: datetime | None = None
    confirmed_at: datetime | None = None
    submitted_at: datetime | None = None
    updated_at: datetime | None = None


# ── Action requests ─────────────────────────────────────────────────────────


class ConfirmRequest(BaseModel):
    """POST /confirm — user must explicitly acknowledge the risk
    warning. The ``risk_acknowledged`` flag is required true."""

    risk_acknowledged: bool


# ── Submission record ──────────────────────────────────────────────────────


class LiveOrderSubmission(BaseModel):
    id: str
    user_id: str
    account_id: str
    live_order_intent_id: str
    broker: str = "SSI"
    broker_order_id: str | None = None
    request_payload_sanitized: dict = Field(default_factory=dict)
    response_payload_sanitized: dict = Field(default_factory=dict)
    status: LiveOrderSubmissionStatus
    submitted_at: datetime
    created_at: datetime


# ── Aggregator response (combined intent + last submission) ────────────────


ValidationStatus = Literal["VALID", "WARN", "REJECTED"]


class LiveOrderIntentResult(BaseModel):
    """Response envelope from preview / request-confirmation / submit /
    cancel. Carries the intent + a structured outcome the UI can read
    without re-fetching."""

    intent: LiveOrderIntent
    validation_status: ValidationStatus
    rejection_reasons: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)

    # Set to true only when an actual SSI submission would have run AND
    # the 5-flag env gate was open. ALWAYS false in Phase 2.8 dry-run.
    is_live_submission_performed: bool = False
    is_dry_run: bool = True
    submission: LiveOrderSubmission | None = None

    # The five env flags + recent re-auth state — the UI uses these to
    # decide whether to show the DRY RUN label vs the strong live warning.
    gate_status: dict = Field(default_factory=dict)
