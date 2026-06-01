"""Phase 2.9 guarded auto-trading engine orchestrator.

Single entry point: ``process_tick``. The route layer (worker-tick)
calls this with a run + a list of candidate (symbol, action, qty)
tuples. The engine:

  1. Verifies the run is in an accepting state.
  2. Verifies the user's auto-trade mode + Phase 2.6 settings.
  3. For each candidate:
     a. Fetch context (quote, security, cash, position).
     b. Compute cooldown + daily counters.
     c. Run the 12+ risk checks (services.auto_trade_risk).
     d. If REJECTED → persist decision (SKIPPED_BY_RISK / SKIPPED_COOLDOWN
        / SKIPPED_MARKET_CLOSED / SKIPPED_KILL_SWITCH …) + audit row.
     e. If VALID/WARN → dispatch based on mode:
        * PAPER_ONLY → call ``services.paper_trading.simulate_paper_order``
        * LIVE_MANUAL_CONFIRM → insert a DRAFT ``live_order_intents`` row
          (the user will walk the Phase 2.8 flow manually). NO submit.
        * LIVE_AUTO + dry-run → record an order row with mode=LIVE_DRY_RUN
          and a synthetic broker response. NEVER call SSI.
        * LIVE_AUTO + live (all 5 Phase-2.8 flags + the Phase-2.9
          worker/live/dry-run flags + per-account ``trading_enabled``)
          → invoke the Phase 2.8 orchestrator's submit-time path.

The engine NEVER bypasses the Phase 2.8 ``submit_live_order_intent``
gauntlet — it walks the same state machine programmatically. The
"auto" affordance is that the user doesn't manually click confirm;
the rest of the safety stack runs identically.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

from core.config import Settings
from core.security import AuthContext
from providers.market_data import MarketDataProvider, ProviderError
from providers.trading import TradingProvider, TradingProviderError
from schemas.auto_trade_engine import (
    AutoTradeDecision,
    AutoTradeOrder,
    DecisionOutcome,
    TickResult,
    WorkerTickRequest,
)
from services.auto_trade_risk import (
    EngineRiskContext,
    validate_engine_decision,
)
from services.auto_trade_scheduler import (
    cooldown_remaining_seconds,
    vn_market_is_open,
)
from services.live_orders import compute_gate_status
from services.supabase_db import SupabaseDB


# ── Helpers ─────────────────────────────────────────────────────────────────


async def _resolve_run(
    db: SupabaseDB, user: AuthContext, run_id: str
) -> dict[str, Any]:
    rows = await db.select(
        "auto_trade_runs",
        where={"id": run_id, "user_id": user.user_id},
        user_jwt=user.raw_token,
    )
    if not rows:
        raise RuntimeError(f"Run {run_id} not owned by user.")
    return rows[0]


async def _build_context(
    *,
    db: SupabaseDB,
    user: AuthContext,
    market: MarketDataProvider,
    trading: TradingProvider,
    settings: Settings,
    run_row: dict[str, Any],
    candidate: dict[str, Any],
) -> EngineRiskContext:
    account_id = run_row["account_id"]
    symbol = (candidate.get("symbol") or "").upper()

    # Auto-trade settings + state (Phase 2.6).
    settings_rows = await db.select(
        "auto_trade_settings",
        where={"user_id": user.user_id, "account_id": account_id},
        user_jwt=user.raw_token,
    )
    state_rows = await db.select(
        "auto_trade_state",
        where={"user_id": user.user_id, "account_id": account_id},
        user_jwt=user.raw_token,
    )
    user_mode = (
        settings_rows[0].get("mode") if settings_rows else "OFF"
    ) or "OFF"

    quote = None
    security = None
    cash = None
    position = None
    try:
        quotes = await market.get_latest_quotes([symbol])
        quote = quotes[0] if quotes else None
    except ProviderError:
        pass
    try:
        security = await market.get_security_details(symbol)
    except ProviderError:
        pass
    try:
        cash = await trading.get_cash_balance(account_id)
    except TradingProviderError:
        pass
    try:
        positions = await trading.get_stock_positions(account_id)
        position = next(
            (p for p in positions if p.symbol.upper() == symbol), None
        )
    except TradingProviderError:
        pass

    # Cooldown — read recent auto_trade_orders for this (account, symbol)
    # action. To keep this minimal we read ALL recent rows for the
    # account and filter by joining to the decision in the cooldown
    # helper would be ideal, but for the minimum-viable engine we
    # read the orders + their associated decisions.
    orders_rows = await db.select(
        "auto_trade_orders",
        where={"account_id": account_id, "user_id": user.user_id},
        user_jwt=user.raw_token,
    )
    # Map: only consider orders whose linked decision is for the same
    # (symbol, action). Read the decisions in one batch.
    decision_ids = {o.get("decision_id") for o in orders_rows if o.get("decision_id")}
    decisions_by_id: dict[str, dict] = {}
    if decision_ids:
        # FakeSupabaseDB and PostgREST both support ``where`` equality
        # only; we filter in Python.
        rows = await db.select(
            "auto_trade_decisions",
            where={"user_id": user.user_id, "account_id": account_id},
            user_jwt=user.raw_token,
        )
        for r in rows:
            decisions_by_id[r["id"]] = r
    relevant_orders = []
    for o in orders_rows:
        d = decisions_by_id.get(o.get("decision_id"))
        if not d:
            continue
        if (
            (d.get("symbol") or "").upper() == symbol
            and (d.get("action") or "").upper()
            == (candidate.get("action") or "").upper()
        ):
            relevant_orders.append(o)
    cooldown_remaining = cooldown_remaining_seconds(
        recent_orders=relevant_orders,
        symbol=symbol,
        action=candidate.get("action") or "",
        cooldown_minutes=settings.auto_trade_symbol_cooldown_minutes,
    )

    # Daily counters (today only).
    today = datetime.now(timezone.utc).date()
    counter_rows = await db.select(
        "auto_trade_risk_counters",
        where={
            "user_id": user.user_id,
            "account_id": account_id,
            "trading_date": today.isoformat(),
        },
        user_jwt=user.raw_token,
    )
    if counter_rows:
        orders_today = int(counter_rows[0].get("orders_count") or 0)
        gross_today = float(counter_rows[0].get("gross_order_value") or 0)
    else:
        orders_today = 0
        gross_today = 0.0

    return EngineRiskContext(
        settings=settings,
        run_row=run_row,
        user_mode=user_mode,
        auto_trade_state_row=state_rows[0] if state_rows else None,
        auto_trade_settings_row=settings_rows[0] if settings_rows else None,
        candidate=candidate,
        quote=quote,
        security=security,
        cash=cash,
        position=position,
        avg_value_20d=None,
        cooldown_seconds_remaining=cooldown_remaining,
        orders_today_count=orders_today,
        gross_order_value_today=gross_today,
    )


# ── Decision persistence ───────────────────────────────────────────────────


async def _persist_decision(
    db: SupabaseDB,
    user: AuthContext,
    run_row: dict[str, Any],
    candidate: dict[str, Any],
    *,
    outcome: DecisionOutcome,
    reasons: list[str],
    snapshot: dict,
) -> dict[str, Any]:
    row = await db.insert(
        "auto_trade_decisions",
        {
            "user_id": user.user_id,
            "account_id": run_row["account_id"],
            "run_id": run_row["id"],
            "symbol": (candidate.get("symbol") or "").upper(),
            "recommendation_id": candidate.get("recommendation_id"),
            "action": (candidate.get("action") or "").upper(),
            "decision": outcome,
            "reason": {"reasons": reasons},
            "risk_snapshot": snapshot,
        },
        user_jwt=user.raw_token,
    )
    # Phase 2.9 review fix: emit the audit row that closes the
    # ``AUTO_TRADE_DECISION_MADE`` / ``AUTO_TRADE_RISK_REJECTED`` enum
    # discrepancy. Best-effort — never blocks the decision.
    try:
        action = (
            "AUTO_TRADE_RISK_REJECTED"
            if outcome.startswith("SKIPPED")
            else "AUTO_TRADE_DECISION_MADE"
        )
        await db.insert(
            "trading_audit_logs",
            {
                "user_id": user.user_id,
                "account_id": run_row["account_id"],
                "action": action,
                "metadata": {
                    "run_id": run_row["id"],
                    "decision_id": row.get("id"),
                    "symbol": (candidate.get("symbol") or "").upper(),
                    "action": (candidate.get("action") or "").upper(),
                    "outcome": outcome,
                },
            },
            user_jwt=user.raw_token,
        )
    except Exception:  # pragma: no cover
        pass
    return row


async def _persist_order(
    db: SupabaseDB,
    user: AuthContext,
    run_row: dict[str, Any],
    decision_id: str,
    *,
    mode: str,
    status: str,
    live_order_intent_id: str | None = None,
    paper_order_id: str | None = None,
) -> dict[str, Any]:
    return await db.insert(
        "auto_trade_orders",
        {
            "user_id": user.user_id,
            "account_id": run_row["account_id"],
            "run_id": run_row["id"],
            "decision_id": decision_id,
            "live_order_intent_id": live_order_intent_id,
            "paper_order_id": paper_order_id,
            "mode": mode,
            "status": status,
        },
        user_jwt=user.raw_token,
    )


async def _bump_counter(
    db: SupabaseDB,
    user: AuthContext,
    account_id: str,
    *,
    gross_value: float,
) -> None:
    today = datetime.now(timezone.utc).date().isoformat()
    rows = await db.select(
        "auto_trade_risk_counters",
        where={
            "user_id": user.user_id,
            "account_id": account_id,
            "trading_date": today,
        },
        user_jwt=user.raw_token,
    )
    if rows:
        r = rows[0]
        new_count = int(r.get("orders_count") or 0) + 1
        new_gross = float(r.get("gross_order_value") or 0) + gross_value
        await db.update(
            "auto_trade_risk_counters",
            {
                "orders_count": new_count,
                "gross_order_value": new_gross,
            },
            where={
                "id": r["id"],
                "user_id": user.user_id,
            },
            user_jwt=user.raw_token,
        )
    else:
        await db.insert(
            "auto_trade_risk_counters",
            {
                "user_id": user.user_id,
                "account_id": account_id,
                "trading_date": today,
                "orders_count": 1,
                "gross_order_value": gross_value,
            },
            user_jwt=user.raw_token,
        )


# ── Mode-specific dispatch ─────────────────────────────────────────────────


async def _dispatch_paper(
    db: SupabaseDB,
    user: AuthContext,
    market: MarketDataProvider,
    trading: TradingProvider,
    run_row: dict[str, Any],
    candidate: dict[str, Any],
) -> tuple[str, str | None]:
    """Find the user's default paper account and create a paper order
    via the existing Phase 2.7 simulator. Returns (status, paper_order_id).
    """
    from services.paper_trading import simulate_paper_order

    paper_accounts = await db.select(
        "paper_accounts",
        where={"user_id": user.user_id},
        user_jwt=user.raw_token,
    )
    if not paper_accounts:
        return ("REJECTED_NO_PAPER_ACCOUNT", None)
    paper_account_id = paper_accounts[0]["id"]
    order_row, fill_row, rejection = await simulate_paper_order(
        db=db, user=user, provider=market,
        paper_account_id=paper_account_id,
        symbol=(candidate.get("symbol") or "").upper(),
        side=(candidate.get("action") or "").upper(),
        order_type=candidate.get("order_type") or "MARKET",
        quantity=int(candidate.get("quantity") or 0),
        limit_price=candidate.get("limit_price"),
        source_type="STRATEGY",
        source_id=run_row["id"],
    )
    return (rejection or "FILLED", order_row.get("id"))


async def _dispatch_manual_confirm(
    db: SupabaseDB,
    user: AuthContext,
    run_row: dict[str, Any],
    candidate: dict[str, Any],
) -> tuple[str, str]:
    """Insert a DRAFT live_order_intent. NO preview, NO submit — the
    user walks the Phase 2.8 flow manually. The engine just queues
    the intent for human attention.
    """
    row = await db.insert(
        "live_order_intents",
        {
            "user_id": user.user_id,
            "account_id": run_row["account_id"],
            "source_type": "STRATEGY",
            "source_id": run_row["id"],
            "symbol": (candidate.get("symbol") or "").upper(),
            "side": (candidate.get("action") or "").upper(),
            "order_type": candidate.get("order_type") or "LIMIT",
            "quantity": int(candidate.get("quantity") or 0),
            "limit_price": candidate.get("limit_price"),
            "status": "DRAFT",
        },
        user_jwt=user.raw_token,
    )
    return ("DRAFT", row["id"])


async def _dispatch_live_auto(
    db: SupabaseDB,
    user: AuthContext,
    market: MarketDataProvider,
    trading: TradingProvider,
    settings: Settings,
    run_row: dict[str, Any],
    candidate: dict[str, Any],
    *,
    dry_run: bool,
) -> tuple[str, str, bool]:
    """LIVE_AUTO branch.

    The engine ALWAYS inserts a live_order_intent (audit), walks it
    through PREVIEWED → CONFIRM_REQUIRED → CONFIRMED, then either:

      * dry_run=True  → mark a synthetic broker response, intent
        transitions to SUBMITTED with mode=LIVE_DRY_RUN.
      * dry_run=False → invoke provider.submit_order (which currently
        raises 501 — Phase 3 wires real SSI). Intent transitions to
        SUBMITTED on success or FAILED on broker error.

    Phase 2.9 review fix (CRITICAL): before invoking provider in the
    live (non-dry-run) branch, this also re-checks the per-account
    ``trading_accounts.trading_enabled`` flag — same defence-in-depth
    as Phase 2.8's manual-confirm path. Without this, an account with
    ``trading_enabled=False`` could be live-submitted by the engine
    once Phase 3 wires real SSI HTTP.

    Returns ``(status, intent_id, is_real_submission)``.
    """
    intent_row = await db.insert(
        "live_order_intents",
        {
            "user_id": user.user_id,
            "account_id": run_row["account_id"],
            "source_type": "STRATEGY",
            "source_id": run_row["id"],
            "symbol": (candidate.get("symbol") or "").upper(),
            "side": (candidate.get("action") or "").upper(),
            "order_type": candidate.get("order_type") or "LIMIT",
            "quantity": int(candidate.get("quantity") or 0),
            "limit_price": candidate.get("limit_price"),
            "status": "DRAFT",
        },
        user_jwt=user.raw_token,
    )
    # Programmatic state walk — the engine acts as the "user" but the
    # transitions still need to be persisted so the audit row reflects
    # the canonical state machine.
    intent_id = intent_row["id"]

    async def _flip(target_status: str, extra: dict | None = None) -> None:
        patch: dict[str, Any] = {
            "status": target_status,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        if extra:
            patch.update(extra)
        await db.update(
            "live_order_intents", patch,
            where={"id": intent_id, "user_id": user.user_id},
            user_jwt=user.raw_token,
        )

    await _flip("PREVIEWED")
    await _flip("CONFIRM_REQUIRED")
    await _flip("CONFIRMED", {"confirmed_at": datetime.now(timezone.utc).isoformat()})

    if dry_run:
        await _flip("SUBMITTED", {"submitted_at": datetime.now(timezone.utc).isoformat()})
        await db.insert(
            "live_order_submissions",
            {
                "user_id": user.user_id,
                "account_id": run_row["account_id"],
                "live_order_intent_id": intent_id,
                "broker": "SSI",
                "request_payload_sanitized": {
                    "symbol": candidate.get("symbol"),
                    "side": candidate.get("action"),
                    "quantity": candidate.get("quantity"),
                    "limit_price": candidate.get("limit_price"),
                },
                "response_payload_sanitized": {
                    "dry_run": True,
                    "engine": "phase_2_9",
                },
                "status": "DRY_RUN_OK",
            },
            user_jwt=user.raw_token,
        )
        return ("DRY_RUN_OK", intent_id, False)

    # Phase 2.9 review fix (CRITICAL): per-account live-trading kill
    # switch must be on before we contact the broker.
    acc_rows = await db.select(
        "trading_accounts",
        where={"id": run_row["account_id"], "user_id": user.user_id},
        user_jwt=user.raw_token,
    )
    if not acc_rows or not acc_rows[0].get("trading_enabled"):
        await _flip("FAILED", {
            "rejection_reasons": ["ACCOUNT_NOT_LIVE_ENABLED"],
        })
        await db.insert(
            "live_order_submissions",
            {
                "user_id": user.user_id,
                "account_id": run_row["account_id"],
                "live_order_intent_id": intent_id,
                "broker": "SSI",
                "request_payload_sanitized": {
                    "symbol": candidate.get("symbol"),
                    "side": candidate.get("action"),
                    "quantity": candidate.get("quantity"),
                    "limit_price": candidate.get("limit_price"),
                },
                "response_payload_sanitized": {
                    "rejection_reasons": ["ACCOUNT_NOT_LIVE_ENABLED"],
                },
                "status": "REJECTED_BY_GATE",
            },
            user_jwt=user.raw_token,
        )
        return ("ACCOUNT_NOT_LIVE_ENABLED", intent_id, False)

    # Live path — invoke provider. Phase 3 wires real SSI.
    try:
        response = await trading.submit_order(
            account_id=run_row["account_id"],
            symbol=(candidate.get("symbol") or "").upper(),
            side=(candidate.get("action") or "").upper(),
            order_type=candidate.get("order_type") or "LIMIT",
            quantity=int(candidate.get("quantity") or 0),
            limit_price=candidate.get("limit_price"),
        )
        await _flip("SUBMITTED", {"submitted_at": datetime.now(timezone.utc).isoformat()})
        await db.insert(
            "live_order_submissions",
            {
                "user_id": user.user_id,
                "account_id": run_row["account_id"],
                "live_order_intent_id": intent_id,
                "broker": "SSI",
                "broker_order_id": response.get("broker_order_id"),
                "request_payload_sanitized": {
                    "symbol": candidate.get("symbol"),
                    "side": candidate.get("action"),
                    "quantity": candidate.get("quantity"),
                    "limit_price": candidate.get("limit_price"),
                },
                "response_payload_sanitized": response,
                "status": "LIVE_OK",
            },
            user_jwt=user.raw_token,
        )
        return ("LIVE_OK", intent_id, True)
    except Exception as exc:
        # Both TradingProviderError (501 today) and any other exception
        # land the intent in FAILED — matching Phase 2.8 fix-cycle.
        await _flip("FAILED", {
            "rejection_reasons": [
                f"BROKER_ERROR_{getattr(exc, 'status_code', 502)}"
            ],
        })
        await db.insert(
            "live_order_submissions",
            {
                "user_id": user.user_id,
                "account_id": run_row["account_id"],
                "live_order_intent_id": intent_id,
                "broker": "SSI",
                "request_payload_sanitized": {
                    "symbol": candidate.get("symbol"),
                    "side": candidate.get("action"),
                    "quantity": candidate.get("quantity"),
                    "limit_price": candidate.get("limit_price"),
                },
                "response_payload_sanitized": {
                    "error_class": type(exc).__name__,
                    "status_code": getattr(exc, "status_code", 502),
                },
                "status": "BROKER_ERROR",
            },
            user_jwt=user.raw_token,
        )
        return (
            f"BROKER_ERROR_{getattr(exc, 'status_code', 502)}",
            intent_id,
            False,
        )


# ── The orchestrator ───────────────────────────────────────────────────────


async def process_tick(
    *,
    db: SupabaseDB,
    user: AuthContext,
    market: MarketDataProvider,
    trading: TradingProvider,
    settings: Settings,
    request: WorkerTickRequest,
) -> TickResult:
    """Walk each candidate through risk + dispatch.

    The route layer enforces auth, ownership, and the worker-enabled
    flag BEFORE calling this. The orchestrator trusts the route did
    those checks but verifies the run is still in an accepting state.
    """
    run_row = await _resolve_run(db, user, request.run_id)
    gate = compute_gate_status(settings)

    # Phase 2.9 review fix (HIGH): enforce ``auto_trade_max_runtime_minutes``.
    # If the run has been running longer than the cap, refuse new
    # decisions AND flip the run to STOPPED so the next tick can't try
    # again — operator must explicitly restart.
    max_runtime_min = settings.auto_trade_max_runtime_minutes
    started_at_raw = run_row.get("started_at")
    if started_at_raw and max_runtime_min > 0:
        from datetime import timedelta as _td
        try:
            if isinstance(started_at_raw, str):
                started_at_dt = datetime.fromisoformat(
                    started_at_raw.replace("Z", "+00:00")
                )
            else:
                started_at_dt = started_at_raw
            age = datetime.now(timezone.utc) - started_at_dt
            if age > _td(minutes=max_runtime_min):
                # Auto-stop. Best-effort — if the state-transition trigger
                # blocks (terminal already), just refuse the tick.
                try:
                    await db.update(
                        "auto_trade_runs",
                        {
                            "status": "STOPPED",
                            "stopped_at": datetime.now(timezone.utc).isoformat(),
                            "updated_at": datetime.now(timezone.utc).isoformat(),
                        },
                        where={
                            "id": run_row["id"],
                            "user_id": user.user_id,
                            "status": run_row.get("status"),
                        },
                        user_jwt=user.raw_token,
                    )
                    await db.insert(
                        "trading_audit_logs",
                        {
                            "user_id": user.user_id,
                            "account_id": run_row["account_id"],
                            "action": "AUTO_TRADE_RUN_STOPPED",
                            "metadata": {
                                "run_id": run_row["id"],
                                "reason": "MAX_RUNTIME_EXCEEDED",
                                "age_minutes": int(age.total_seconds() // 60),
                                "max_minutes": max_runtime_min,
                            },
                        },
                        user_jwt=user.raw_token,
                    )
                except Exception:  # pragma: no cover
                    pass
                return TickResult(
                    run_id=request.run_id,
                    decisions=[], orders=[],
                    skipped_count=0, dispatched_count=0,
                    is_dry_run=settings.auto_trade_dry_run,
                    gate_status=gate.to_dict(),
                )
        except ValueError:
            pass

    # Cap candidates per tick. The route also enforces this; belt+braces.
    max_per_tick = settings.auto_trade_max_decisions_per_tick
    candidates = list(request.candidates)[:max_per_tick]

    decisions: list[AutoTradeDecision] = []
    orders: list[AutoTradeOrder] = []
    skipped_count = 0
    dispatched_count = 0

    for cand in candidates:
        ctx = await _build_context(
            db=db, user=user, market=market, trading=trading,
            settings=settings, run_row=run_row, candidate=cand,
        )
        result = validate_engine_decision(ctx)

        if result.status == "REJECTED":
            # Map specific reason → SKIPPED_* outcome for nicer UI.
            outcome: DecisionOutcome = "SKIPPED_BY_RISK"
            joined = " ".join(result.reasons)
            if "KILL_SWITCH_ACTIVE" in joined:
                outcome = "SKIPPED_KILL_SWITCH"
            elif "MARKET_CLOSED" in joined:
                outcome = "SKIPPED_MARKET_CLOSED"
            elif "COOLDOWN_ACTIVE" in joined:
                outcome = "SKIPPED_COOLDOWN"
            elif "DATA_UNAVAILABLE" in joined or "QUOTE_STALE" in joined:
                outcome = "SKIPPED_DATA_STALE"
            elif (
                "SYMBOL_NOT_ALLOWED" in joined
                or "STRATEGY_NOT_ALLOWED" in joined
                or "ACTION_NOT_ALLOWED" in joined
            ):
                outcome = "SKIPPED_NOT_ALLOWED"

            decision_row = await _persist_decision(
                db, user, run_row, cand,
                outcome=outcome,
                reasons=result.reasons,
                snapshot=result.snapshot,
            )
            decisions.append(AutoTradeDecision(**decision_row))
            skipped_count += 1
            continue

        # ── VALID/WARN → dispatch ──
        mode = ctx.user_mode
        if mode == "PAPER_ONLY":
            status, paper_id = await _dispatch_paper(
                db, user, market, trading, run_row, cand,
            )
            decision_row = await _persist_decision(
                db, user, run_row, cand,
                outcome="DISPATCHED_PAPER",
                reasons=[],
                snapshot=result.snapshot,
            )
            order_row = await _persist_order(
                db, user, run_row, decision_row["id"],
                mode="PAPER", status=status, paper_order_id=paper_id,
            )
        elif mode == "LIVE_MANUAL_CONFIRM":
            status, intent_id = await _dispatch_manual_confirm(
                db, user, run_row, cand,
            )
            decision_row = await _persist_decision(
                db, user, run_row, cand,
                outcome="DISPATCHED_MANUAL_CONFIRM",
                reasons=[],
                snapshot=result.snapshot,
            )
            order_row = await _persist_order(
                db, user, run_row, decision_row["id"],
                mode="MANUAL_CONFIRM", status=status,
                live_order_intent_id=intent_id,
            )
        elif mode == "LIVE_AUTO":
            # The 5-flag gate AND Phase 2.9 worker/live/dry-run flags
            # AND the per-account ``trading_enabled`` must all align
            # for the live path. Otherwise → dry-run.
            is_live = (
                gate.all_open
                and settings.auto_trade_live_enabled
                and settings.auto_trade_order_placement_enabled
                and not settings.auto_trade_dry_run
            )
            status, intent_id, did_live = await _dispatch_live_auto(
                db, user, market, trading, settings, run_row, cand,
                dry_run=not is_live,
            )
            outcome: DecisionOutcome = (
                "DISPATCHED_LIVE" if did_live else "DISPATCHED_LIVE_DRY_RUN"
            )
            decision_row = await _persist_decision(
                db, user, run_row, cand,
                outcome=outcome,
                reasons=[],
                snapshot=result.snapshot,
            )
            order_row = await _persist_order(
                db, user, run_row, decision_row["id"],
                mode="LIVE" if did_live else "LIVE_DRY_RUN",
                status=status,
                live_order_intent_id=intent_id,
            )
        else:
            # OFF or unsupported mode — SKIP.
            decision_row = await _persist_decision(
                db, user, run_row, cand,
                outcome="SKIPPED_NOT_RECOMMENDED",
                reasons=[f"MODE_NOT_RUNNABLE: {mode}"],
                snapshot=result.snapshot,
            )
            decisions.append(AutoTradeDecision(**decision_row))
            skipped_count += 1
            continue

        # Bump the daily counter on every dispatched candidate.
        if ctx.quote and ctx.quote.price:
            gross = float(ctx.quote.price) * int(cand.get("quantity") or 0)
        else:
            gross = float(cand.get("limit_price") or 0) * int(
                cand.get("quantity") or 0
            )
        await _bump_counter(db, user, run_row["account_id"], gross_value=gross)

        decisions.append(AutoTradeDecision(**decision_row))
        orders.append(AutoTradeOrder(**order_row))
        dispatched_count += 1

    return TickResult(
        run_id=request.run_id,
        decisions=decisions,
        orders=orders,
        skipped_count=skipped_count,
        dispatched_count=dispatched_count,
        is_dry_run=settings.auto_trade_dry_run,
        gate_status=gate.to_dict(),
    )
