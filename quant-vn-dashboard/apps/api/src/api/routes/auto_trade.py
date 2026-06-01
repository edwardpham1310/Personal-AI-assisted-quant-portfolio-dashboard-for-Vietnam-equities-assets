"""Phase 2.6 Auto-trade safety-foundation routes.

ALL routes are mode-selection / risk-limit configuration / state inspection.
NONE submit a real broker order. The two-flag environment kill switch
(``AUTO_TRADE_LIVE_ENABLED`` + ``AUTO_TRADE_ORDER_PLACEMENT_ENABLED``)
remains false in Phase 2.6 and is enforced at startup by
``_assert_production_auto_trade_disabled``.

Audit semantics: every mode-change and every settings update writes a
row to ``trading_audit_logs`` with an ``AUTO_TRADE_*`` action. Reads
are also audit-stamped (``AUTO_TRADE_SETTINGS_VIEWED``) so an operator
can investigate "who looked at the limits before the change".
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status

from fastapi import Header

from core.config import Settings, get_settings
from core.deps import get_db, get_market_provider, get_trading_provider
from core.logging import get_logger
from core.security import AuthContext, get_current_user
from providers.market_data import MarketDataProvider
from providers.trading import TradingProvider
from schemas.auto_trade import (
    AutoTradeAuditAction,
    AutoTradeAuditEntry,
    AutoTradeMode,
    AutoTradeSettings,
    AutoTradeSettingsUpdate,
    AutoTradeState,
    EmergencyStopRequest,
    LiveAutoEnableConfirm,
    LiveAutoRequestResult,
    ModeTransitionRequest,
    ModeTransitionResult,
)
from services.auto_trade import (
    apply_settings_update,
    is_live_execution_enabled,
    reauth_is_fresh,
    sanitize_audit_reasons,
    validate_live_auto_prerequisites,
    validate_manual_confirm_prerequisites,
    validate_paper_only_prerequisites,
)
from services.supabase_db import SupabaseDB

logger = get_logger(__name__)
router = APIRouter()


# ── Helpers ─────────────────────────────────────────────────────────────────


async def _audit(
    db: SupabaseDB,
    user: AuthContext,
    action: AutoTradeAuditAction,
    request: Request,
    account_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    """Best-effort persistent audit log + structured Python log.

    Never raises — audit failures must not block the user's request.
    Mirrors the pattern from ``api/routes/trading.py``.
    """
    logger.info(
        "auto_trade.audit user=%s action=%s account=%s metadata_keys=%s",
        user.user_id,
        action,
        account_id,
        list((metadata or {}).keys()),
    )
    payload = {
        "user_id": user.user_id,
        "account_id": account_id,
        "action": action,
        "metadata": metadata or {},
        "ip_address": (
            request.client.host if request and request.client else None
        ),
        "user_agent": (
            request.headers.get("user-agent") if request else None
        ),
    }
    try:
        await db.insert("trading_audit_logs", payload, user_jwt=user.raw_token)
    except Exception as exc:  # pragma: no cover - audit must never block
        logger.warning(
            "auto_trade.audit_persist_failed action=%s err=%s",
            action,
            type(exc).__name__,
        )


async def _resolve_user_account(
    db: SupabaseDB, user: AuthContext, account_id: str
) -> dict[str, Any]:
    """Same belt-and-suspenders pattern as routes/trading.py:
    explicit ``user_id`` filter + RLS at the DB layer.
    """
    rows = await db.select(
        "trading_accounts",
        where={"id": account_id, "user_id": user.user_id},
        user_jwt=user.raw_token,
    )
    if not rows:
        raise HTTPException(status_code=404, detail="Trading account not found.")
    return rows[0]


async def _get_or_create_settings_row(
    db: SupabaseDB, user: AuthContext, account_id: str
) -> AutoTradeSettings:
    rows = await db.select(
        "auto_trade_settings",
        where={"user_id": user.user_id, "account_id": account_id},
        user_jwt=user.raw_token,
    )
    if rows:
        return AutoTradeSettings(**rows[0])
    created = await db.insert(
        "auto_trade_settings",
        {
            "user_id": user.user_id,
            "account_id": account_id,
            "mode": "OFF",
            "enabled": False,
        },
        user_jwt=user.raw_token,
    )
    return AutoTradeSettings(**created)


async def _get_or_create_state_row(
    db: SupabaseDB, user: AuthContext, account_id: str
) -> AutoTradeState:
    rows = await db.select(
        "auto_trade_state",
        where={"user_id": user.user_id, "account_id": account_id},
        user_jwt=user.raw_token,
    )
    if rows:
        return AutoTradeState(**rows[0])
    created = await db.insert(
        "auto_trade_state",
        {
            "user_id": user.user_id,
            "account_id": account_id,
            "mode": "OFF",
            "is_running": False,
        },
        user_jwt=user.raw_token,
    )
    return AutoTradeState(**created)


async def _persist_mode_transition(
    db: SupabaseDB,
    user: AuthContext,
    account_id: str,
    *,
    new_mode: AutoTradeMode,
    enabled: bool,
    extra_settings_patch: dict[str, Any] | None = None,
) -> tuple[AutoTradeSettings, AutoTradeState]:
    """Atomically (per the fake/real DB layer) update both rows.

    The ``trading_audit_logs`` write is the responsibility of the route
    that called this helper — see each handler.
    """
    settings_patch = {"mode": new_mode, "enabled": enabled}
    if extra_settings_patch:
        settings_patch.update(extra_settings_patch)
    settings_rows = await db.update(
        "auto_trade_settings",
        settings_patch,
        where={"user_id": user.user_id, "account_id": account_id},
        user_jwt=user.raw_token,
    )
    now = datetime.now(timezone.utc).isoformat()
    state_patch: dict[str, Any] = {"mode": new_mode}
    if new_mode == "OFF":
        state_patch["is_running"] = False
        state_patch["last_stopped_at"] = now
    state_rows = await db.update(
        "auto_trade_state",
        state_patch,
        where={"user_id": user.user_id, "account_id": account_id},
        user_jwt=user.raw_token,
    )
    settings = AutoTradeSettings(**settings_rows[0]) if settings_rows else AutoTradeSettings(
        user_id=user.user_id, account_id=account_id, mode=new_mode, enabled=enabled
    )
    state = AutoTradeState(**state_rows[0]) if state_rows else AutoTradeState(
        user_id=user.user_id, account_id=account_id, mode=new_mode
    )
    return settings, state


# ── GET /auto-trade/settings ───────────────────────────────────────────────


@router.get("/settings", response_model=AutoTradeSettings)
async def get_settings_row(
    account_id: str,
    request: Request,
    user: AuthContext = Depends(get_current_user),
    db: SupabaseDB = Depends(get_db),
) -> AutoTradeSettings:
    await _resolve_user_account(db, user, account_id)
    row = await _get_or_create_settings_row(db, user, account_id)
    await _audit(
        db, user, "AUTO_TRADE_SETTINGS_VIEWED", request, account_id=account_id
    )
    return row


@router.put("/settings", response_model=AutoTradeSettings)
async def update_settings_row(
    account_id: str,
    payload: AutoTradeSettingsUpdate,
    request: Request,
    user: AuthContext = Depends(get_current_user),
    db: SupabaseDB = Depends(get_db),
) -> AutoTradeSettings:
    await _resolve_user_account(db, user, account_id)
    current = await _get_or_create_settings_row(db, user, account_id)
    patch = apply_settings_update(current, payload)
    if not patch:
        return current
    updated_rows = await db.update(
        "auto_trade_settings",
        patch,
        where={"user_id": user.user_id, "account_id": account_id},
        user_jwt=user.raw_token,
    )
    await _audit(
        db, user, "AUTO_TRADE_SETTINGS_UPDATED", request,
        account_id=account_id,
        metadata={"fields_updated": list(patch.keys())},
    )
    return AutoTradeSettings(**updated_rows[0])


# ── GET /auto-trade/state ──────────────────────────────────────────────────


@router.get("/state", response_model=AutoTradeState)
async def get_state_row(
    account_id: str,
    user: AuthContext = Depends(get_current_user),
    db: SupabaseDB = Depends(get_db),
) -> AutoTradeState:
    await _resolve_user_account(db, user, account_id)
    return await _get_or_create_state_row(db, user, account_id)


# ── POST /auto-trade/reauth ────────────────────────────────────────────────


@router.post("/reauth")
async def stamp_reauth(
    account_id: str,
    request: Request,
    user: AuthContext = Depends(get_current_user),
    db: SupabaseDB = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    """Stamp ``last_reauth_at`` IFF the JWT's ``iat`` proves the user
    just signed in.

    The frontend calls ``supabase.auth.signInWithPassword`` first; the
    refreshed JWT has a fresh ``iat``. The backend never sees the
    password. If the JWT iat is stale, return 401 + audit a failure.
    """
    await _resolve_user_account(db, user, account_id)
    fresh = reauth_is_fresh(
        settings=settings, jwt_claims=user.claims, last_reauth_at=None
    )
    if not fresh:
        await _audit(
            db, user, "AUTO_TRADE_REAUTH_FAILED", request,
            account_id=account_id,
            metadata={"reason": "JWT_IAT_STALE"},
        )
        raise HTTPException(
            status_code=401,
            detail="Re-authentication required. Please re-enter your password.",
        )
    # Ensure a settings row exists before writing — otherwise the UPDATE
    # would silently no-op (return []) and the audit row below would
    # claim success while ``last_reauth_at`` was never persisted.
    await _get_or_create_settings_row(db, user, account_id)
    now = datetime.now(timezone.utc).isoformat()
    rows = await db.update(
        "auto_trade_settings",
        {"last_reauth_at": now},
        where={"user_id": user.user_id, "account_id": account_id},
        user_jwt=user.raw_token,
    )
    if not rows:  # defence-in-depth: should never trigger after _get_or_create
        await _audit(
            db, user, "AUTO_TRADE_REAUTH_FAILED", request,
            account_id=account_id,
            metadata={"reason": "PERSIST_FAILED_NO_ROW"},
        )
        raise HTTPException(status_code=500, detail="Re-auth could not be persisted.")
    await _audit(
        db, user, "AUTO_TRADE_REAUTH_SUCCESS", request,
        account_id=account_id,
    )
    return {
        "ok": True,
        "last_reauth_at": now,
        "valid_for_seconds": settings.auto_trade_reauth_max_age_seconds,
    }


# ── Mode transitions ───────────────────────────────────────────────────────


@router.post("/enable-paper", response_model=ModeTransitionResult)
async def enable_paper(
    payload: ModeTransitionRequest,
    request: Request,
    user: AuthContext = Depends(get_current_user),
    db: SupabaseDB = Depends(get_db),
    env_settings: Settings = Depends(get_settings),
) -> ModeTransitionResult:
    await _resolve_user_account(db, user, payload.account_id)
    current = await _get_or_create_settings_row(db, user, payload.account_id)
    await _get_or_create_state_row(db, user, payload.account_id)
    reasons = validate_paper_only_prerequisites(
        settings_row=current, env_settings=env_settings
    )
    if reasons:
        # Audit the REJECT path with the same action so a probe leaves a
        # trail. ``sanitize_audit_reasons`` keeps the persisted metadata
        # to stable enum codes; the HTTP response keeps the full strings.
        await _audit(
            db, user, "AUTO_TRADE_ENABLE_PAPER", request,
            account_id=payload.account_id,
            metadata={
                "validation_status": "REJECTED",
                "reasons": sanitize_audit_reasons(reasons),
            },
        )
        return ModeTransitionResult(
            account_id=payload.account_id,
            mode=current.mode,
            validation_status="REJECTED",
            rejection_reasons=reasons,
            is_live_execution_enabled=False,
        )
    settings, _ = await _persist_mode_transition(
        db, user, payload.account_id, new_mode="PAPER_ONLY", enabled=True,
    )
    await _audit(
        db, user, "AUTO_TRADE_ENABLE_PAPER", request,
        account_id=payload.account_id,
        metadata={"previous_mode": current.mode},
    )
    return ModeTransitionResult(
        account_id=payload.account_id,
        mode=settings.mode,
        validation_status="VALID",
        is_live_execution_enabled=is_live_execution_enabled(env_settings),
        last_reauth_at=settings.last_reauth_at,
        risk_acknowledged_at=settings.risk_acknowledged_at,
    )


@router.post("/enable-manual-confirm", response_model=ModeTransitionResult)
async def enable_manual_confirm(
    payload: ModeTransitionRequest,
    request: Request,
    user: AuthContext = Depends(get_current_user),
    db: SupabaseDB = Depends(get_db),
    env_settings: Settings = Depends(get_settings),
) -> ModeTransitionResult:
    await _resolve_user_account(db, user, payload.account_id)
    current = await _get_or_create_settings_row(db, user, payload.account_id)
    await _get_or_create_state_row(db, user, payload.account_id)
    reauth_ok = reauth_is_fresh(
        settings=env_settings,
        jwt_claims=user.claims,
        last_reauth_at=current.last_reauth_at,
    )
    reasons = validate_manual_confirm_prerequisites(
        settings_row=current,
        reauth_fresh=reauth_ok,
        env_settings=env_settings,
    )
    if reasons:
        await _audit(
            db, user, "AUTO_TRADE_ENABLE_MANUAL_CONFIRM_REQUESTED", request,
            account_id=payload.account_id,
            metadata={
                "validation_status": "REJECTED",
                "reasons": sanitize_audit_reasons(reasons),
            },
        )
        return ModeTransitionResult(
            account_id=payload.account_id,
            mode=current.mode,
            validation_status="REJECTED",
            rejection_reasons=reasons,
            is_live_execution_enabled=False,
            last_reauth_at=current.last_reauth_at,
        )
    settings, _ = await _persist_mode_transition(
        db, user, payload.account_id,
        new_mode="LIVE_MANUAL_CONFIRM", enabled=True,
    )
    await _audit(
        db, user, "AUTO_TRADE_ENABLE_MANUAL_CONFIRM_REQUESTED", request,
        account_id=payload.account_id,
        metadata={"validation_status": "VALID", "previous_mode": current.mode},
    )
    return ModeTransitionResult(
        account_id=payload.account_id,
        mode=settings.mode,
        validation_status="VALID",
        is_live_execution_enabled=is_live_execution_enabled(env_settings),
        last_reauth_at=settings.last_reauth_at,
        risk_acknowledged_at=settings.risk_acknowledged_at,
    )


@router.post(
    "/request-live-auto-enable", response_model=LiveAutoRequestResult
)
async def request_live_auto_enable(
    payload: ModeTransitionRequest,
    request: Request,
    user: AuthContext = Depends(get_current_user),
    db: SupabaseDB = Depends(get_db),
    env_settings: Settings = Depends(get_settings),
) -> LiveAutoRequestResult:
    """Step 1 of the LIVE_AUTO flow. Validates every prerequisite EXCEPT
    the explicit risk acknowledgement, so the UI can render the
    blocker list before showing the risk modal."""
    await _resolve_user_account(db, user, payload.account_id)
    current = await _get_or_create_settings_row(db, user, payload.account_id)
    await _get_or_create_state_row(db, user, payload.account_id)
    reauth_ok = reauth_is_fresh(
        settings=env_settings,
        jwt_claims=user.claims,
        last_reauth_at=current.last_reauth_at,
    )
    reasons = validate_live_auto_prerequisites(
        settings_row=current,
        risk_acknowledged=True,  # checked again on confirm
        reauth_fresh=reauth_ok,
        env_settings=env_settings,
    )
    is_valid = not reasons
    await _audit(
        db, user, "AUTO_TRADE_ENABLE_LIVE_AUTO_REQUESTED", request,
        account_id=payload.account_id,
        metadata={
            "validation_status": "VALID" if is_valid else "REJECTED",
            "reasons": sanitize_audit_reasons(reasons),
        },
    )
    return LiveAutoRequestResult(
        account_id=payload.account_id,
        mode=current.mode,
        validation_status="VALID" if is_valid else "REJECTED",
        rejection_reasons=reasons,
        is_live_execution_enabled=False,
        last_reauth_at=current.last_reauth_at,
        risk_acknowledged_at=current.risk_acknowledged_at,
        next_step="CONFIRM_RISK_ACKNOWLEDGEMENT" if is_valid else "ABORT",
    )


@router.post("/confirm-live-auto-enable", response_model=ModeTransitionResult)
async def confirm_live_auto_enable(
    payload: LiveAutoEnableConfirm,
    request: Request,
    user: AuthContext = Depends(get_current_user),
    db: SupabaseDB = Depends(get_db),
    env_settings: Settings = Depends(get_settings),
) -> ModeTransitionResult:
    """Step 2 of the LIVE_AUTO flow. Re-validates ALL prerequisites
    (defence-in-depth: never trust step 1's "valid" alone) and persists
    the mode change.

    NOTE: even after this completes, ``is_live_execution_enabled`` stays
    false in Phase 2.6 — the env-level kill switches remain disabled.
    """
    await _resolve_user_account(db, user, payload.account_id)
    current = await _get_or_create_settings_row(db, user, payload.account_id)
    await _get_or_create_state_row(db, user, payload.account_id)
    reauth_ok = reauth_is_fresh(
        settings=env_settings,
        jwt_claims=user.claims,
        last_reauth_at=current.last_reauth_at,
    )
    reasons = validate_live_auto_prerequisites(
        settings_row=current,
        risk_acknowledged=payload.risk_acknowledged,
        reauth_fresh=reauth_ok,
        env_settings=env_settings,
    )
    if reasons:
        await _audit(
            db, user, "AUTO_TRADE_LIVE_AUTO_CONFIRMED", request,
            account_id=payload.account_id,
            metadata={
                "validation_status": "REJECTED",
                "reasons": sanitize_audit_reasons(reasons),
            },
        )
        return ModeTransitionResult(
            account_id=payload.account_id,
            mode=current.mode,
            validation_status="REJECTED",
            rejection_reasons=reasons,
            is_live_execution_enabled=False,
            last_reauth_at=current.last_reauth_at,
            risk_acknowledged_at=current.risk_acknowledged_at,
        )
    now = datetime.now(timezone.utc).isoformat()
    settings, _ = await _persist_mode_transition(
        db, user, payload.account_id,
        new_mode="LIVE_AUTO", enabled=True,
        extra_settings_patch={"risk_acknowledged_at": now},
    )
    await _audit(
        db, user, "AUTO_TRADE_LIVE_AUTO_CONFIRMED", request,
        account_id=payload.account_id,
        metadata={"validation_status": "VALID", "previous_mode": current.mode},
    )
    return ModeTransitionResult(
        account_id=payload.account_id,
        mode=settings.mode,
        validation_status="VALID",
        is_live_execution_enabled=is_live_execution_enabled(env_settings),
        last_reauth_at=settings.last_reauth_at,
        risk_acknowledged_at=settings.risk_acknowledged_at,
    )


@router.post("/disable", response_model=ModeTransitionResult)
async def disable_auto_trade(
    payload: ModeTransitionRequest,
    request: Request,
    user: AuthContext = Depends(get_current_user),
    db: SupabaseDB = Depends(get_db),
    env_settings: Settings = Depends(get_settings),
) -> ModeTransitionResult:
    await _resolve_user_account(db, user, payload.account_id)
    current = await _get_or_create_settings_row(db, user, payload.account_id)
    await _get_or_create_state_row(db, user, payload.account_id)
    settings, _ = await _persist_mode_transition(
        db, user, payload.account_id, new_mode="OFF", enabled=False,
    )
    await _audit(
        db, user, "AUTO_TRADE_DISABLED", request,
        account_id=payload.account_id,
        metadata={"previous_mode": current.mode},
    )
    return ModeTransitionResult(
        account_id=payload.account_id,
        mode=settings.mode,
        validation_status="VALID",
        is_live_execution_enabled=False,
        last_reauth_at=settings.last_reauth_at,
        risk_acknowledged_at=settings.risk_acknowledged_at,
    )


@router.post("/emergency-stop", response_model=ModeTransitionResult)
async def emergency_stop(
    payload: EmergencyStopRequest,
    request: Request,
    user: AuthContext = Depends(get_current_user),
    db: SupabaseDB = Depends(get_db),
    env_settings: Settings = Depends(get_settings),
) -> ModeTransitionResult:
    """Hard kill switch. Sets mode OFF, is_running=false, records the
    reason + timestamp. Does NOT cancel/submit broker orders (Phase
    2.6: there are no live orders to cancel).
    """
    await _resolve_user_account(db, user, payload.account_id)
    current = await _get_or_create_settings_row(db, user, payload.account_id)
    await _get_or_create_state_row(db, user, payload.account_id)
    now = datetime.now(timezone.utc).isoformat()
    await db.update(
        "auto_trade_settings",
        {"mode": "OFF", "enabled": False},
        where={"user_id": user.user_id, "account_id": payload.account_id},
        user_jwt=user.raw_token,
    )
    await db.update(
        "auto_trade_state",
        {
            "mode": "OFF",
            "is_running": False,
            "emergency_stopped_at": now,
            "emergency_stop_reason": payload.reason,
            "last_stopped_at": now,
        },
        where={"user_id": user.user_id, "account_id": payload.account_id},
        user_jwt=user.raw_token,
    )
    await _audit(
        db, user, "AUTO_TRADE_EMERGENCY_STOP", request,
        account_id=payload.account_id,
        metadata={"previous_mode": current.mode, "reason": payload.reason},
    )
    return ModeTransitionResult(
        account_id=payload.account_id,
        mode="OFF",
        validation_status="VALID",
        is_live_execution_enabled=False,
        last_reauth_at=current.last_reauth_at,
        risk_acknowledged_at=current.risk_acknowledged_at,
    )


# ── GET /auto-trade/audit-logs ─────────────────────────────────────────────


_AUDIT_LOGS_DEFAULT_LIMIT = 100
_AUDIT_LOGS_MAX_LIMIT = 500


@router.get("/audit-logs", response_model=list[AutoTradeAuditEntry])
async def list_audit_logs(
    request: Request,
    account_id: str | None = None,
    limit: int = _AUDIT_LOGS_DEFAULT_LIMIT,
    user: AuthContext = Depends(get_current_user),
    db: SupabaseDB = Depends(get_db),
) -> list[AutoTradeAuditEntry]:
    """Return the user's auto-trade audit rows (latest first).

    Filtering by ``account_id`` is optional; without it the caller sees
    every account's history.

    Bounded by ``limit`` (default 100, max 500) so a user with a long
    audit history can't pull an unbounded result set. Reading the audit
    log writes an ``AUTO_TRADE_AUDIT_VIEWED`` row so a forensics
    investigator can answer "who saw what when" — without this, a
    stolen JWT could enumerate the user's whole mode-change history
    leaving no trail of the read.
    """
    if limit < 1:
        limit = 1
    if limit > _AUDIT_LOGS_MAX_LIMIT:
        limit = _AUDIT_LOGS_MAX_LIMIT
    where: dict[str, Any] = {"user_id": user.user_id}
    if account_id:
        where["account_id"] = account_id
    rows = await db.select(
        "trading_audit_logs", where=where, user_jwt=user.raw_token
    )
    auto_only = [
        r for r in rows
        if isinstance(r.get("action"), str)
        and r["action"].startswith("AUTO_TRADE_")
    ]
    auto_only.sort(
        key=lambda r: r.get("created_at") or "", reverse=True
    )
    auto_only = auto_only[:limit]
    await _audit(
        db, user, "AUTO_TRADE_AUDIT_VIEWED", request,
        account_id=account_id,
        metadata={"rows_returned": len(auto_only), "limit": limit},
    )
    return [AutoTradeAuditEntry(**r) for r in auto_only]


# ── Phase 2.9 Guarded auto-trading engine ──────────────────────────────────
#
# The engine is orchestrated by ``services.auto_trade_engine.process_tick``.
# The route layer only enforces auth + ownership + the worker-enabled
# env flag, then delegates. There is NO background daemon.


from schemas.auto_trade_engine import (
    AutoTradeDecision,
    AutoTradeOrder,
    AutoTradeRiskCounter,
    AutoTradeRun,
    RunStartRequest,
    TickResult,
    WorkerTickRequest,
)


def _is_legal_run_transition(current: str, target: str) -> bool:
    allowed = {
        "STARTED": {"RUNNING", "STOPPED", "EMERGENCY_STOPPED", "FAILED"},
        "RUNNING": {"PAUSED", "STOPPED", "EMERGENCY_STOPPED", "FAILED"},
        "PAUSED": {"RUNNING", "STOPPED", "EMERGENCY_STOPPED", "FAILED"},
        "STOPPED": set(),
        "EMERGENCY_STOPPED": set(),
        "FAILED": set(),
    }
    return target in allowed.get(current, set())


@router.post(
    "/runs/start",
    response_model=AutoTradeRun,
    status_code=status.HTTP_201_CREATED,
)
async def start_run(
    payload: RunStartRequest,
    request: Request,
    user: AuthContext = Depends(get_current_user),
    db: SupabaseDB = Depends(get_db),
    env_settings: Settings = Depends(get_settings),
) -> AutoTradeRun:
    """Create + start a run. The run reflects the user's current
    auto-trade mode. Refused if the mode is OFF.
    """
    # Resolve account ownership via the existing trading-account check.
    acc_rows = await db.select(
        "trading_accounts",
        where={"id": payload.account_id, "user_id": user.user_id},
        user_jwt=user.raw_token,
    )
    if not acc_rows:
        raise HTTPException(status_code=404, detail="Trading account not found.")

    settings_rows = await db.select(
        "auto_trade_settings",
        where={"user_id": user.user_id, "account_id": payload.account_id},
        user_jwt=user.raw_token,
    )
    mode = (settings_rows[0].get("mode") if settings_rows else "OFF") or "OFF"
    if mode == "OFF":
        raise HTTPException(
            status_code=400,
            detail="Auto-trade mode is OFF for this account. Set a mode first.",
        )

    now = datetime.now(timezone.utc).isoformat()
    row = await db.insert(
        "auto_trade_runs",
        {
            "user_id": user.user_id,
            "account_id": payload.account_id,
            "mode": mode,
            "strategy_id": payload.strategy_id,
            "status": "RUNNING",
            "started_at": now,
            "metadata": payload.metadata,
        },
        user_jwt=user.raw_token,
    )
    await _audit(
        db, user, "AUTO_TRADE_RUN_STARTED", request,
        account_id=payload.account_id,
        metadata={"run_id": row["id"], "mode": mode, "strategy_id": payload.strategy_id},
    )
    return AutoTradeRun(**row)


@router.get("/runs", response_model=list[AutoTradeRun])
async def list_runs(
    account_id: str | None = None,
    user: AuthContext = Depends(get_current_user),
    db: SupabaseDB = Depends(get_db),
) -> list[AutoTradeRun]:
    where: dict[str, Any] = {"user_id": user.user_id}
    if account_id:
        where["account_id"] = account_id
    rows = await db.select(
        "auto_trade_runs", where=where, user_jwt=user.raw_token,
    )
    rows.sort(key=lambda r: r.get("created_at") or r.get("started_at") or "", reverse=True)
    return [AutoTradeRun(**r) for r in rows]


async def _transition_run(
    db: SupabaseDB,
    user: AuthContext,
    run_id: str,
    *,
    target: str,
    extra: dict | None = None,
) -> dict[str, Any]:
    rows = await db.select(
        "auto_trade_runs",
        where={"id": run_id, "user_id": user.user_id},
        user_jwt=user.raw_token,
    )
    if not rows:
        raise HTTPException(status_code=404, detail="Run not found.")
    current = rows[0].get("status")
    if not _is_legal_run_transition(current, target):
        raise HTTPException(
            status_code=409,
            detail=f"Illegal run transition {current} → {target}",
        )
    patch = {"status": target, "updated_at": datetime.now(timezone.utc).isoformat()}
    if target in ("STOPPED", "EMERGENCY_STOPPED", "FAILED"):
        patch["stopped_at"] = datetime.now(timezone.utc).isoformat()
    if extra:
        patch.update(extra)
    updated = await db.update(
        "auto_trade_runs", patch,
        where={"id": run_id, "user_id": user.user_id, "status": current},
        user_jwt=user.raw_token,
    )
    if not updated:
        raise HTTPException(
            status_code=409, detail="State changed concurrently."
        )
    return updated[0]


@router.post("/runs/stop", response_model=AutoTradeRun)
async def stop_run(
    run_id: str,
    request: Request,
    user: AuthContext = Depends(get_current_user),
    db: SupabaseDB = Depends(get_db),
) -> AutoTradeRun:
    updated = await _transition_run(db, user, run_id, target="STOPPED")
    await _audit(
        db, user, "AUTO_TRADE_RUN_STOPPED", request,
        account_id=updated["account_id"],
        metadata={"run_id": run_id},
    )
    return AutoTradeRun(**updated)


@router.post("/runs/pause", response_model=AutoTradeRun)
async def pause_run(
    run_id: str,
    request: Request,
    user: AuthContext = Depends(get_current_user),
    db: SupabaseDB = Depends(get_db),
) -> AutoTradeRun:
    updated = await _transition_run(db, user, run_id, target="PAUSED")
    await _audit(
        db, user, "AUTO_TRADE_RUN_PAUSED", request,
        account_id=updated["account_id"],
        metadata={"run_id": run_id},
    )
    return AutoTradeRun(**updated)


@router.get("/decisions", response_model=list[AutoTradeDecision])
async def list_decisions(
    run_id: str | None = None,
    account_id: str | None = None,
    limit: int = 100,
    user: AuthContext = Depends(get_current_user),
    db: SupabaseDB = Depends(get_db),
) -> list[AutoTradeDecision]:
    if limit < 1:
        limit = 1
    if limit > 500:
        limit = 500
    where: dict[str, Any] = {"user_id": user.user_id}
    if run_id:
        where["run_id"] = run_id
    if account_id:
        where["account_id"] = account_id
    rows = await db.select(
        "auto_trade_decisions", where=where, user_jwt=user.raw_token,
    )
    rows.sort(key=lambda r: r.get("created_at") or "", reverse=True)
    return [AutoTradeDecision(**r) for r in rows[:limit]]


@router.get("/orders", response_model=list[AutoTradeOrder])
async def list_engine_orders(
    run_id: str | None = None,
    account_id: str | None = None,
    limit: int = 100,
    user: AuthContext = Depends(get_current_user),
    db: SupabaseDB = Depends(get_db),
) -> list[AutoTradeOrder]:
    if limit < 1:
        limit = 1
    if limit > 500:
        limit = 500
    where: dict[str, Any] = {"user_id": user.user_id}
    if run_id:
        where["run_id"] = run_id
    if account_id:
        where["account_id"] = account_id
    rows = await db.select(
        "auto_trade_orders", where=where, user_jwt=user.raw_token,
    )
    rows.sort(key=lambda r: r.get("created_at") or "", reverse=True)
    return [AutoTradeOrder(**r) for r in rows[:limit]]


@router.get("/risk-counters", response_model=list[AutoTradeRiskCounter])
async def list_risk_counters(
    account_id: str | None = None,
    user: AuthContext = Depends(get_current_user),
    db: SupabaseDB = Depends(get_db),
) -> list[AutoTradeRiskCounter]:
    where: dict[str, Any] = {"user_id": user.user_id}
    if account_id:
        where["account_id"] = account_id
    rows = await db.select(
        "auto_trade_risk_counters", where=where, user_jwt=user.raw_token,
    )
    rows.sort(key=lambda r: r.get("trading_date") or "", reverse=True)
    return [AutoTradeRiskCounter(**r) for r in rows]


@router.post("/worker/tick", response_model=TickResult)
async def worker_tick(
    payload: WorkerTickRequest,
    request: Request,
    x_worker_secret: str | None = Header(default=None, alias="X-Worker-Secret"),
    user: AuthContext = Depends(get_current_user),
    db: SupabaseDB = Depends(get_db),
    market: MarketDataProvider = Depends(get_market_provider),
    trading: TradingProvider = Depends(get_trading_provider),
    env_settings: Settings = Depends(get_settings),
) -> TickResult:
    """The engine's single entry point.

    Auth: ALWAYS requires a valid user JWT (``Depends(get_current_user)``).
    Additionally, if ``AUTO_TRADE_WORKER_SECRET`` is set, the request
    must also carry an ``X-Worker-Secret`` header matching it — this
    lets cron / k8s CronJob runners authenticate while preventing
    unauthenticated probes from triggering the engine.

    Refused if ``AUTO_TRADE_WORKER_ENABLED=false`` — the per-env kill
    switch is independent of the per-user run state.
    """
    if not env_settings.auto_trade_worker_enabled:
        await _audit(
            db, user, "AUTO_TRADE_WORKER_TICK_BLOCKED", request,
            account_id=None,
            metadata={
                "run_id": payload.run_id,
                "reason": "WORKER_DISABLED",
            },
        )
        raise HTTPException(
            status_code=503,
            detail="Auto-trade worker is disabled at the environment level.",
        )

    expected = env_settings.auto_trade_worker_secret
    if expected:
        # Phase 2.9 review fix (CRITICAL): use constant-time comparison
        # so a short-enough secret can't be brute-forced via timing
        # side channel. Both inputs must be ``str``; ``hmac.compare_digest``
        # requires equal length but tolerates any length difference safely.
        import hmac as _hmac
        provided = x_worker_secret or ""
        if not _hmac.compare_digest(provided.encode(), expected.encode()):
            await _audit(
                db, user, "AUTO_TRADE_WORKER_TICK_BLOCKED", request,
                account_id=None,
                metadata={
                    "run_id": payload.run_id,
                    "reason": "BAD_WORKER_SECRET",
                },
            )
            raise HTTPException(
                status_code=401,
                detail="Worker secret missing or incorrect.",
            )

    # Run-ownership is verified by the orchestrator (resolves with the
    # same user_id filter).
    from services.auto_trade_engine import process_tick

    await _audit(
        db, user, "AUTO_TRADE_WORKER_TICK", request,
        account_id=None,
        metadata={
            "run_id": payload.run_id,
            "candidate_count": len(payload.candidates),
        },
    )
    try:
        result = await process_tick(
            db=db, user=user, market=market, trading=trading,
            settings=env_settings, request=payload,
        )
    except RuntimeError as exc:
        # Phase 2.9 review fix (CRITICAL): the engine's _resolve_run
        # raises RuntimeError("Run X not owned by user.") when a user
        # supplies someone else's run_id. Previously this fell through
        # to the generic 502 handler — leaking via the wrong status
        # code AND skipping the FAILED-state transition (since the run
        # isn't ours, we shouldn't touch it). Surface as 404.
        if "not owned" in str(exc).lower():
            raise HTTPException(status_code=404, detail="Run not found.")
        raise
    except Exception as exc:
        # Engine-side failure → flip the run to FAILED so the next tick
        # can't accidentally proceed on a corrupted state.
        try:
            await _transition_run(db, user, payload.run_id, target="FAILED")
        except HTTPException:
            pass
        await _audit(
            db, user, "AUTO_TRADE_RUN_FAILED", request,
            account_id=None,
            metadata={
                "run_id": payload.run_id,
                "error_class": type(exc).__name__,
            },
        )
        raise HTTPException(status_code=502, detail="Engine tick failed.")
    return result
