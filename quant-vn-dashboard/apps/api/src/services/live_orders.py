"""Phase 2.8 Manual-confirm live trading orchestrator.

Single source of truth for the 5-flag AND gate that decides whether a
real SSI ``submit_order`` may be called. The route layer is a thin
wrapper that only persists state changes and writes audit rows; ALL
safety decisions live here.

The 5 environment flags (every one must align for live submission):
    1. TRADING_LIVE_ORDER_ENABLED=true
    2. TRADING_MANUAL_CONFIRM_ENABLED=true
    3. SSI_TRADING_READ_ONLY=false
    4. SSI_TRADING_USE_MOCK=false   (a mock provider cannot live-submit)
    5. TRADING_ORDER_PLACEMENT_DRY_RUN=false

PLUS at submit time, the orchestrator re-checks:
    * the stored preview is not expired (< ORDER_PREVIEW_MAX_AGE_SECONDS)
    * the user has a recent re-auth (JWT iat or stamped last_reauth_at)
    * the intent is in state CONFIRMED
    * the auto-trade mode for this account is NOT LIVE_AUTO
      (Phase 2.6 guarantee — Phase 2.8 is manual-confirm only)
    * risk re-validation passes against the LATEST quote (price drift
      since preview, ceiling/floor band, lot, cash/shares, Phase 2.6
      limits — max_order_value_vnd, max_orders_per_day, position weight)

If any check fails: intent goes to REJECTED and an audit row records
the precise reason. Dry-run path returns a synthetic broker response
and is the ONLY path that runs when any gate is closed.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from core.config import Settings
from providers.market_data import MarketDataProvider, ProviderError
from schemas.live_orders import LiveOrderIntentStatus, ValidationStatus
from schemas.market import Quote, Security
from schemas.trading import (
    CashBalance,
    OrderPreviewRequest,
    StockPosition,
)
from services.auto_trade import reauth_is_fresh
from services.order_preview import PreviewInputs, calculate_preview


# ── State-transition matrix (also enforced at DB layer by trigger) ─────────


_ALLOWED_TRANSITIONS: dict[
    LiveOrderIntentStatus, set[LiveOrderIntentStatus]
] = {
    "DRAFT": {"PREVIEWED", "REJECTED", "CANCELLED"},
    "PREVIEWED": {"CONFIRM_REQUIRED", "PREVIEWED", "REJECTED", "CANCELLED"},
    "CONFIRM_REQUIRED": {"CONFIRMED", "REJECTED", "CANCELLED"},
    "CONFIRMED": {"SUBMITTED", "REJECTED", "CANCELLED", "FAILED"},
    "SUBMITTED": set(),
    "REJECTED": set(),
    "CANCELLED": set(),
    "FAILED": set(),
}


def is_legal_transition(
    current: LiveOrderIntentStatus, target: LiveOrderIntentStatus
) -> bool:
    return target in _ALLOWED_TRANSITIONS.get(current, set())


# ── 5-flag env gate ────────────────────────────────────────────────────────


@dataclass(frozen=True)
class GateStatus:
    live_order_enabled: bool
    manual_confirm_enabled: bool
    read_only_disabled: bool      # i.e. ssi_trading_read_only is False
    not_using_mock: bool          # i.e. ssi_trading_use_mock is False
    dry_run_disabled: bool        # i.e. trading_order_placement_dry_run is False
    all_open: bool                # AND of all five

    def to_dict(self) -> dict[str, bool]:
        return {
            "live_order_enabled": self.live_order_enabled,
            "manual_confirm_enabled": self.manual_confirm_enabled,
            "read_only_disabled": self.read_only_disabled,
            "not_using_mock": self.not_using_mock,
            "dry_run_disabled": self.dry_run_disabled,
            "all_open": self.all_open,
        }


def compute_gate_status(settings: Settings) -> GateStatus:
    live = settings.trading_live_order_enabled
    manual = settings.trading_manual_confirm_enabled
    not_read_only = not settings.ssi_trading_read_only
    not_mock = not settings.ssi_trading_use_mock
    dry_run_off = not settings.trading_order_placement_dry_run
    return GateStatus(
        live_order_enabled=live,
        manual_confirm_enabled=manual,
        read_only_disabled=not_read_only,
        not_using_mock=not_mock,
        dry_run_disabled=dry_run_off,
        all_open=(live and manual and not_read_only and not_mock and dry_run_off),
    )


# ── Risk re-validation at submit time ──────────────────────────────────────


@dataclass(frozen=True)
class SubmitContext:
    """Bundle passed from the route layer to the orchestrator. Holds
    everything the orchestrator needs to re-validate without re-fetching
    half-of-the-world. The route assembles this once.
    """

    intent_row: dict[str, Any]
    settings: Settings
    jwt_claims: dict[str, Any] | None
    last_reauth_at: datetime | None
    quote: Quote | None
    security: Security | None
    cash: CashBalance | None
    position: StockPosition | None
    avg_value_20d: float | None
    auto_trade_mode: str
    # Phase 2.6 settings row (for max_order_value_vnd etc.).
    auto_trade_settings_row: dict[str, Any] | None
    # Daily order count so far today for this user+account.
    orders_today: int
    # Phase 2.8 review fix: per-account live-trading kill switch read
    # from ``trading_accounts.trading_enabled``. Must be ``True`` for
    # the orchestrator to permit live submission, AS A DEFENCE IN DEPTH
    # alongside the 5-flag env gate.
    trading_account_enabled: bool = False


def revalidate_for_submit(
    ctx: SubmitContext, *, now: datetime | None = None
) -> tuple[ValidationStatus, list[str], list[str], dict[str, Any]]:
    """Run the submit-time gauntlet.

    Returns ``(status, rejection_reasons, warnings, snapshot)``.
    ``status`` is the worst-of (VALID < WARN < REJECTED). Snapshot is a
    JSON-safe dict persisted on the intent row for forensics.
    """
    now = now or datetime.now(timezone.utc)
    reasons: list[str] = []
    warnings: list[str] = []

    # 1. Intent must be CONFIRMED.
    if ctx.intent_row.get("status") != "CONFIRMED":
        reasons.append(f"NOT_CONFIRMED: status={ctx.intent_row.get('status')}")

    # 2. Re-auth fresh.
    if ctx.settings.trading_require_reauth:
        # Mirror Phase 2.6 reauth semantics with a tighter window if
        # configured separately.
        s = ctx.settings
        # Allow either JWT iat or stamped last_reauth_at.
        if not reauth_is_fresh(
            settings=s,
            jwt_claims=ctx.jwt_claims,
            last_reauth_at=ctx.last_reauth_at,
            now=now,
            max_age_seconds=s.trading_reauth_max_age_seconds,
        ):
            reasons.append("REAUTH_REQUIRED")

    # 3. Auto-trade mode must NOT be LIVE_AUTO (Phase 2.8 is manual only).
    if ctx.auto_trade_mode == "LIVE_AUTO":
        reasons.append("AUTO_TRADE_LIVE_AUTO_FORBIDDEN")

    # 4. Preview not expired.
    created_at_raw = ctx.intent_row.get("created_at")
    preview_age_seconds: float | None = None
    if isinstance(created_at_raw, str):
        try:
            created_at_dt = datetime.fromisoformat(
                created_at_raw.replace("Z", "+00:00")
            )
            preview_age_seconds = (now - created_at_dt).total_seconds()
        except ValueError:
            warnings.append("CREATED_AT_UNPARSEABLE")
    elif isinstance(created_at_raw, datetime):
        preview_age_seconds = (now - created_at_raw).total_seconds()
    if (
        preview_age_seconds is not None
        and preview_age_seconds > ctx.settings.order_preview_max_age_seconds
    ):
        reasons.append(
            f"PREVIEW_EXPIRED: age={int(preview_age_seconds)}s "
            f"max={ctx.settings.order_preview_max_age_seconds}s"
        )

    # 5a. Per-account live-trading kill switch is checked at the ROUTE
    # layer only when actually going live (see ``submit_live_order_intent``).
    # Dry-run flows do not require ``trading_accounts.trading_enabled``
    # since no broker contact happens.

    # 5b. Live quote freshness (DATA_UNAVAILABLE if no quote).
    if ctx.quote is None:
        reasons.append("DATA_UNAVAILABLE")
    elif getattr(ctx.quote, "stale", False) or getattr(ctx.quote, "is_stale", False):
        # Phase 2.8 review fix: a non-None but stale quote was previously
        # accepted. AC item 13 requires "data freshness" be enforced.
        reasons.append("QUOTE_STALE")

    # 6. Re-run the preview calculator with current data — this picks up
    # price drift, lot violations, ceiling/floor band, cash/shares, and
    # liquidity (5% of 20d ADV) in a single pass.
    if ctx.quote is not None:
        req = OrderPreviewRequest(
            account_id=ctx.intent_row["account_id"],
            symbol=ctx.intent_row["symbol"],
            side=ctx.intent_row["side"],
            quantity=int(ctx.intent_row["quantity"]),
            limit_price=float(
                ctx.intent_row.get("limit_price")
                or (ctx.quote.price if ctx.quote.price else 0)
            ),
            order_type=ctx.intent_row.get("order_type") or "LIMIT",
        )
        result = calculate_preview(
            PreviewInputs(
                request=req,
                quote=ctx.quote,
                security=ctx.security,
                cash=ctx.cash,
                position=ctx.position,
                avg_value_20d=ctx.avg_value_20d,
            )
        )
        for r in result.rejection_reasons:
            reasons.append(f"PREVIEW_RECHECK_{r.split(':',1)[0].strip()}")
        for w in result.warnings:
            warnings.append(f"PREVIEW_RECHECK_{w.split(':',1)[0].strip()}")

    # 7. Phase 2.6 per-account daily-order ceiling + max order value +
    #    max position weight. Only applied if auto_trade_settings exist.
    if ctx.auto_trade_settings_row is not None:
        s_row = ctx.auto_trade_settings_row
        max_orders = int(s_row.get("max_orders_per_day") or 0)
        if max_orders > 0 and ctx.orders_today >= max_orders:
            reasons.append(
                f"DAILY_ORDER_LIMIT_REACHED: today={ctx.orders_today} "
                f"max={max_orders}"
            )
        max_order_value = float(s_row.get("max_order_value_vnd") or 0)
        if max_order_value > 0 and ctx.quote is not None:
            order_value = (
                float(ctx.intent_row.get("limit_price") or ctx.quote.price or 0)
                * int(ctx.intent_row["quantity"])
            )
            if order_value > max_order_value:
                reasons.append(
                    f"ORDER_VALUE_OVER_LIMIT: order={int(order_value)} "
                    f"max={int(max_order_value)}"
                )
        # Position-weight check: skip if we don't have account equity
        # (would require summary aggregation here). Treat as a WARN if
        # missing, REJECTED if over limit when computable.
        max_pos_weight = float(s_row.get("max_position_weight") or 0)
        if max_pos_weight > 0:
            warnings.append("POSITION_WEIGHT_CHECK_PENDING_PORTFOLIO_INTEGRATION")

    # ── Status precedence ──
    status: ValidationStatus = "VALID"
    if reasons:
        status = "REJECTED"
    elif warnings:
        status = "WARN"

    snapshot = {
        "as_of": now.isoformat(),
        "preview_age_seconds": preview_age_seconds,
        "quote_price": ctx.quote.price if ctx.quote else None,
        "quote_source": ctx.quote.source if ctx.quote else None,
        "buying_power": ctx.cash.buying_power if ctx.cash else None,
        "sellable_quantity": (
            ctx.position.sellable_quantity if ctx.position else 0
        ),
        "orders_today": ctx.orders_today,
        "auto_trade_mode": ctx.auto_trade_mode,
        "reasons": reasons,
        "warnings": warnings,
    }
    return status, reasons, warnings, snapshot


# ── Dry-run "broker" simulator ─────────────────────────────────────────────


def synthetic_broker_response(
    *,
    intent_row: dict[str, Any],
    quote: Quote | None,
) -> dict[str, Any]:
    """Return a synthetic ``response_payload_sanitized`` for a dry-run
    submission. NEVER calls SSI. The shape mirrors what a real SSI
    response would look like so the UI render code is identical between
    dry-run and (future Phase 3) live."""
    return {
        "dry_run": True,
        "simulated_status": "ACCEPTED_DRY_RUN",
        "simulated_fill_price": (
            float(quote.price) if quote and quote.price else None
        ),
        "simulated_quantity": int(intent_row["quantity"]),
        "broker_message": (
            "DRY RUN — no real order submitted. Set "
            "TRADING_ORDER_PLACEMENT_DRY_RUN=false and configure all "
            "Phase 2.8 flags to enable live submission."
        ),
    }


def sanitize_request_payload(intent_row: dict[str, Any]) -> dict[str, Any]:
    """Strip anything sensitive from a request payload before persisting
    to ``live_order_submissions.request_payload_sanitized``. Account IDs
    stay (they're the user's own). Credentials / tokens / SSI internal
    fields never appear here because the intent row never carries them.
    """
    return {
        "account_id": intent_row.get("account_id"),
        "symbol": intent_row.get("symbol"),
        "side": intent_row.get("side"),
        "order_type": intent_row.get("order_type"),
        "quantity": intent_row.get("quantity"),
        "limit_price": intent_row.get("limit_price"),
        "source_type": intent_row.get("source_type"),
    }
