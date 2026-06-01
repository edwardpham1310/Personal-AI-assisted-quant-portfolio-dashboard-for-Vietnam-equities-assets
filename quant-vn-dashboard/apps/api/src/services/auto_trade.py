"""Auto-trade state machine + re-auth verification + risk validation.

Pure / lightly-stateful service used by ``api/routes/auto_trade.py``.
Contains no I/O of its own beyond what's passed in — the route layer
owns the database and audit log calls.

Phase 2.6 invariants enforced here:
* Mode transitions follow a strict matrix (see ``ALLOWED_TRANSITIONS``).
* ``LIVE_MANUAL_CONFIRM`` requires recent re-auth.
* ``LIVE_AUTO`` requires recent re-auth + all risk limits set +
  non-empty allow-lists + explicit risk acknowledgement +
  ``AUTO_TRADE_LIVE_ENABLED=true`` from env.
* ``is_live_execution_enabled`` is ALWAYS false (executions remain
  disabled by environment in Phase 2.6).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from core.config import Settings
from schemas.auto_trade import (
    AutoTradeMode,
    AutoTradeSettings,
    AutoTradeSettingsUpdate,
)


# ── Mode transition policy ──────────────────────────────────────────────────
# Phase 2.6 deliberately allows any-to-any mode transitions. The gates are
# the prerequisite validators below (re-auth + risk limits + risk-ack), not
# the source state. This lets a user in LIVE_AUTO drop back to PAPER or OFF
# instantly — the "fast safety descent" property the spec calls for.
#
# An earlier draft exposed an ``ALLOWED_TRANSITIONS`` dict that no route or
# service ever consulted. It was deleted to remove the false implication
# of source-state enforcement.


# ── Re-auth verification ────────────────────────────────────────────────────


def reauth_is_fresh(
    *,
    settings: Settings,
    jwt_claims: dict[str, Any] | None = None,
    last_reauth_at: datetime | None = None,
    now: datetime | None = None,
    max_age_seconds: int | None = None,
) -> bool:
    """Return True iff the user has re-authenticated within the configured
    window.

    Two independent proofs are accepted:
      1. ``last_reauth_at`` stamped within the configured window.
      2. The JWT's ``iat`` (issued-at) claim within the same window — this
         is what a fresh ``signInWithPassword`` flow on the frontend
         produces, and proves the user just entered their password (the
         backend never sees the password itself).

    ``max_age_seconds`` defaults to ``auto_trade_reauth_max_age_seconds``;
    Phase 2.8 callers pass ``trading_reauth_max_age_seconds`` so the
    live-trading reauth window is independently configurable.
    """
    now = now or datetime.now(timezone.utc)
    max_age = (
        max_age_seconds
        if max_age_seconds is not None
        else settings.auto_trade_reauth_max_age_seconds
    )

    if last_reauth_at is not None:
        delta = (now - last_reauth_at).total_seconds()
        if 0 <= delta <= max_age:
            return True

    if jwt_claims is not None:
        iat = jwt_claims.get("iat")
        if isinstance(iat, (int, float)):
            age = now.timestamp() - float(iat)
            if 0 <= age <= max_age:
                return True

    return False


# ── Risk-limit validation for LIVE_AUTO ────────────────────────────────────


def validate_live_auto_prerequisites(
    *,
    settings_row: AutoTradeSettings,
    risk_acknowledged: bool,
    reauth_fresh: bool,
    env_settings: Settings,
) -> list[str]:
    """Return a list of rejection reasons (empty list = VALID).

    A single REJECTED reason is enough to block the transition; we
    accumulate so the UI can show every missing requirement in one
    pass instead of forcing the user through repeated round-trips.
    """
    reasons: list[str] = []

    if not env_settings.auto_trade_enabled:
        reasons.append("AUTO_TRADE_DISABLED_AT_ENV: AUTO_TRADE_ENABLED is false")

    if not env_settings.auto_trade_live_enabled:
        reasons.append(
            "LIVE_EXECUTION_DISABLED_AT_ENV: AUTO_TRADE_LIVE_ENABLED is false"
        )

    if not settings_row.account_id:
        reasons.append("ACCOUNT_ID_MISSING")

    if settings_row.max_capital_vnd <= 0:
        reasons.append("MAX_CAPITAL_VND_REQUIRED")
    if settings_row.max_order_value_vnd <= 0:
        reasons.append("MAX_ORDER_VALUE_VND_REQUIRED")
    if settings_row.max_orders_per_day <= 0:
        reasons.append("MAX_ORDERS_PER_DAY_REQUIRED")
    if settings_row.max_daily_loss_vnd <= 0:
        reasons.append("MAX_DAILY_LOSS_VND_REQUIRED")
    if settings_row.max_position_weight <= 0:
        reasons.append("MAX_POSITION_WEIGHT_REQUIRED")

    if not settings_row.allowed_strategies:
        reasons.append("ALLOWED_STRATEGIES_REQUIRED")

    if not settings_row.allowed_symbols and not settings_row.allowed_watchlists:
        reasons.append("ALLOWED_SYMBOLS_OR_WATCHLISTS_REQUIRED")

    if not risk_acknowledged:
        reasons.append("RISK_ACKNOWLEDGEMENT_REQUIRED")

    if not reauth_fresh:
        reasons.append(
            "REAUTH_REQUIRED: please re-enter your password"
        )

    return reasons


def validate_manual_confirm_prerequisites(
    *,
    settings_row: AutoTradeSettings,
    reauth_fresh: bool,
    env_settings: Settings,
) -> list[str]:
    """LIVE_MANUAL_CONFIRM needs auto-trade enabled at env + recent re-auth
    + an account_id. Risk limits are NOT required for manual-confirm mode
    because every order requires a click anyway, but the form still
    encourages them."""
    reasons: list[str] = []

    if not env_settings.auto_trade_enabled:
        reasons.append("AUTO_TRADE_DISABLED_AT_ENV: AUTO_TRADE_ENABLED is false")

    if not settings_row.account_id:
        reasons.append("ACCOUNT_ID_MISSING")

    if not reauth_fresh:
        reasons.append(
            "REAUTH_REQUIRED: please re-enter your password"
        )
    return reasons


def validate_paper_only_prerequisites(
    *,
    settings_row: AutoTradeSettings,
    env_settings: Settings,
) -> list[str]:
    """PAPER_ONLY: only needs auto_trade_enabled at env. No re-auth,
    no risk limits — by definition it's a simulation."""
    reasons: list[str] = []
    if not env_settings.auto_trade_enabled:
        reasons.append("AUTO_TRADE_DISABLED_AT_ENV: AUTO_TRADE_ENABLED is false")
    if not settings_row.account_id:
        reasons.append("ACCOUNT_ID_MISSING")
    return reasons


# ── Merge helper for PUT /settings ─────────────────────────────────────────


_SERVER_OWNED_FIELDS: tuple[str, ...] = (
    # Mode transitions go through their dedicated endpoints.
    "mode",
    "enabled",
    # Re-auth + risk-ack timestamps are stamped by the server only —
    # a client that pre-stamps these would bypass the re-auth window
    # for LIVE_AUTO.
    "last_reauth_at",
    "risk_acknowledged_at",
    # Identity + audit timestamps are NEVER editable.
    "id",
    "user_id",
    "account_id",
    "created_at",
    "updated_at",
)


def apply_settings_update(
    current: AutoTradeSettings, patch: AutoTradeSettingsUpdate
) -> dict[str, Any]:
    """Return the dict of fields to write to the DB row. Only set keys
    in ``patch`` (Pydantic's ``model_dump(exclude_unset=True)``) flow
    through, which keeps PUT semantics partial — the UI can save one
    field at a time without resetting the rest to defaults.

    The ``AutoTradeSettingsUpdate`` DTO already omits server-owned
    fields, so Pydantic's default ``extra="ignore"`` drops them at
    parse-time. The explicit strip list below is defence-in-depth:
    if a future refactor adds one of these fields to the DTO by
    mistake (e.g. someone adds ``last_reauth_at: datetime | None`` for
    a UI bind), the route still cannot persist it without also editing
    this list and getting another code review.
    """
    payload = patch.model_dump(exclude_unset=True)
    for f in _SERVER_OWNED_FIELDS:
        payload.pop(f, None)
    return payload


def sanitize_audit_reasons(reasons: list[str]) -> list[str]:
    """Strip the ``: human-readable description`` tail from each reason
    before persisting to the audit log. The HTTP response keeps the
    full string for UX; the persisted row keeps a stable enum code so
    future ``WHERE action_code = ...`` queries are reliable AND any
    future error string that embeds user-balance / strategy detail
    cannot leak through the audit table.

    Example: ``"REAUTH_REQUIRED: please re-enter your password"`` →
    ``"REAUTH_REQUIRED"``.
    """
    out: list[str] = []
    for r in reasons:
        code = r.split(":", 1)[0].strip()
        out.append(code or r)
    return out


# ── Live-execution invariant ────────────────────────────────────────────────


def is_live_execution_enabled(env_settings: Settings) -> bool:
    """The product-wide kill switch for Phase 2.6.

    Returns True only if BOTH ``auto_trade_live_enabled`` AND
    ``auto_trade_order_placement_enabled`` are true at the env level
    AND ``ssi_trading_order_placement_enabled`` from Phase 2.5 is true.

    In Phase 2.6 production startup guards refuse the first two to be
    true, so the answer is ALWAYS False in any production deployment.
    The function exists so the route layer can return a single boolean
    to the UI without recomputing the AND each time.
    """
    return (
        env_settings.auto_trade_live_enabled
        and env_settings.auto_trade_order_placement_enabled
        and env_settings.ssi_trading_order_placement_enabled
    )
