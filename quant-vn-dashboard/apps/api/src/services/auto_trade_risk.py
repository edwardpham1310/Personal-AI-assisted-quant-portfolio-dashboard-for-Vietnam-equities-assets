"""Phase 2.9 auto-trade risk guardrails — pure-function rule matrix.

The engine builds an ``EngineRiskContext`` once per candidate, then
calls ``validate_engine_decision`` which returns a structured
``RiskValidationResult`` (status + reasons + warnings + snapshot).

Most checks reuse ``services.order_preview.calculate_preview`` so the
fee model, lot size, ceiling/floor band, cash/shares, and liquidity
guardrail are computed identically to manual-confirm and paper.
Engine-specific checks added here:

  * Run is not in a terminal/paused state
  * Auto-trade mode for the account matches the engine's expectation
  * Kill switch not active (state.emergency_stopped_at IS NULL)
  * Symbol is in the allow-list
  * Strategy is in the allow-list
  * Action is allowed (only BUY/SELL — BUY_CANDIDATE/WATCH/HOLD/AVOID
    are reco signals, not orders; the engine maps each into either
    a BUY/SELL or a SKIP)
  * Cooldown not active for (symbol, action)
  * Per-day order count under the Phase 2.6 ceiling
  * Per-day gross-order-value under the ceiling
  * Market open (when configured)
  * Quote not stale + provider didn't fail

These checks are conservative — when in doubt, REJECT.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from core.config import Settings
from schemas.auto_trade_engine import RiskValidationResult, ValidationStatus
from schemas.market import Quote, Security
from schemas.trading import (
    CashBalance,
    OrderPreviewRequest,
    StockPosition,
)
from services.auto_trade_scheduler import vn_market_is_open
from services.order_preview import PreviewInputs, calculate_preview


@dataclass(frozen=True)
class EngineRiskContext:
    """Bundle assembled by the engine before calling the validator."""

    settings: Settings
    run_row: dict[str, Any]              # auto_trade_runs row
    user_mode: str                        # auto_trade_settings.mode
    auto_trade_state_row: dict[str, Any] | None
    auto_trade_settings_row: dict[str, Any] | None
    candidate: dict[str, Any]             # {symbol, action, quantity, limit_price?, recommendation_id?}
    quote: Quote | None
    security: Security | None
    cash: CashBalance | None
    position: StockPosition | None
    avg_value_20d: float | None
    cooldown_seconds_remaining: int
    orders_today_count: int
    gross_order_value_today: float
    now: datetime | None = None


def _worst(cur: ValidationStatus, new: ValidationStatus) -> ValidationStatus:
    order = {"VALID": 0, "WARN": 1, "REJECTED": 2}
    return cur if order[cur] >= order[new] else new


def validate_engine_decision(ctx: EngineRiskContext) -> RiskValidationResult:
    reasons: list[str] = []
    warnings: list[str] = []
    status: ValidationStatus = "VALID"
    now = ctx.now or datetime.now(UTC)

    # 1. Run must be in a state that accepts new decisions.
    run_status = ctx.run_row.get("status")
    if run_status not in ("STARTED", "RUNNING"):
        reasons.append(f"RUN_NOT_ACCEPTING_DECISIONS: status={run_status}")

    # 2. Kill switch (Phase 2.6 emergency stop sets emergency_stopped_at).
    state = ctx.auto_trade_state_row or {}
    if state.get("emergency_stopped_at"):
        reasons.append("KILL_SWITCH_ACTIVE")

    # 3. User auto-trade mode must agree with the run's mode (engine
    #    will refuse if the user's mode changed since the run started).
    if ctx.user_mode != ctx.run_row.get("mode"):
        reasons.append(
            f"MODE_DRIFT: user={ctx.user_mode} run={ctx.run_row.get('mode')}"
        )

    # 4. Action allowed — engine only acts on BUY/SELL candidates.
    action = (ctx.candidate.get("action") or "").upper()
    if action not in ("BUY", "SELL"):
        return RiskValidationResult(
            status="REJECTED",
            reasons=[f"ACTION_NOT_ALLOWED: {action}"],
            warnings=warnings,
            snapshot={"action": action},
        )

    # 5. Symbol allow-list (only enforced if non-empty list configured).
    s_row = ctx.auto_trade_settings_row or {}
    allowed_symbols: list[str] = list(s_row.get("allowed_symbols") or [])
    if allowed_symbols and ctx.candidate.get("symbol", "").upper() not in [
        s.upper() for s in allowed_symbols
    ]:
        reasons.append(f"SYMBOL_NOT_ALLOWED: {ctx.candidate.get('symbol')}")

    # 6. Strategy allow-list.
    allowed_strategies: list[str] = list(s_row.get("allowed_strategies") or [])
    strategy_id = ctx.run_row.get("strategy_id") or "default"
    if allowed_strategies and strategy_id not in allowed_strategies:
        reasons.append(f"STRATEGY_NOT_ALLOWED: {strategy_id}")

    # 7. Cooldown — engine never re-trades the same (symbol, action) inside
    #    AUTO_TRADE_SYMBOL_COOLDOWN_MINUTES.
    if ctx.cooldown_seconds_remaining > 0:
        reasons.append(
            f"COOLDOWN_ACTIVE: {ctx.cooldown_seconds_remaining}s remaining"
        )

    # 8. Per-day order count under Phase 2.6 ceiling.
    max_orders = int(s_row.get("max_orders_per_day") or 0)
    if max_orders > 0 and ctx.orders_today_count >= max_orders:
        reasons.append(
            f"DAILY_ORDER_LIMIT_REACHED: today={ctx.orders_today_count} "
            f"max={max_orders}"
        )

    # 9. Per-single-order value ceiling. Phase 2.9 review fix
    # (CRITICAL): the engine previously skipped this check entirely;
    # Phase 2.8 ``validate_live_auto_prerequisites`` enforces it, but
    # the engine's LIVE_AUTO path bypasses Phase 2.8. A user could thus
    # exceed ``max_order_value_vnd`` via the engine.
    max_order_value = float(s_row.get("max_order_value_vnd") or 0)
    if max_order_value > 0:
        candidate_value_single = (
            float(ctx.candidate.get("limit_price")
                  or (ctx.quote.price if ctx.quote and ctx.quote.price else 0))
            * int(ctx.candidate.get("quantity") or 0)
        )
        if candidate_value_single > max_order_value:
            reasons.append(
                f"ORDER_VALUE_OVER_LIMIT: order={int(candidate_value_single)} "
                f"max={int(max_order_value)}"
            )

    # 9b. Per-day gross-order-value under ceiling.
    max_capital = float(s_row.get("max_capital_vnd") or 0)
    if max_capital > 0:
        candidate_value = (
            float(ctx.candidate.get("limit_price")
                  or (ctx.quote.price if ctx.quote and ctx.quote.price else 0))
            * int(ctx.candidate.get("quantity") or 0)
        )
        if ctx.gross_order_value_today + candidate_value > max_capital:
            reasons.append(
                f"DAILY_GROSS_LIMIT_REACHED: "
                f"would_be={int(ctx.gross_order_value_today + candidate_value)} "
                f"max={int(max_capital)}"
            )

    # 10. Market open (skip if not required).
    if ctx.settings.auto_trade_require_market_open and not vn_market_is_open(now):
        reasons.append("MARKET_CLOSED")

    # 11. Quote freshness — DATA_UNAVAILABLE or QUOTE_STALE.
    if ctx.quote is None:
        reasons.append("DATA_UNAVAILABLE")
    elif getattr(ctx.quote, "stale", False):
        reasons.append("QUOTE_STALE")

    # 12. Re-run the preview-style math when we have a quote — fees,
    # lot, ceiling/floor, cash/shares, liquidity (5% ADV).
    if ctx.quote is not None:
        req = OrderPreviewRequest(
            account_id=ctx.run_row.get("account_id") or "x",
            symbol=ctx.candidate.get("symbol") or "",
            side=action,
            quantity=int(ctx.candidate.get("quantity") or 0),
            limit_price=float(
                ctx.candidate.get("limit_price")
                or (ctx.quote.price if ctx.quote.price else 0)
            ),
            order_type=ctx.candidate.get("order_type") or "LIMIT",
        )
        preview = calculate_preview(
            PreviewInputs(
                request=req,
                quote=ctx.quote,
                security=ctx.security,
                cash=ctx.cash,
                position=ctx.position,
                avg_value_20d=ctx.avg_value_20d,
            )
        )
        for r in preview.rejection_reasons:
            reasons.append(f"PREVIEW_{r.split(':',1)[0].strip()}")
        for w in preview.warnings:
            warnings.append(f"PREVIEW_{w.split(':',1)[0].strip()}")

    if reasons:
        status = "REJECTED"
    elif warnings:
        status = _worst(status, "WARN")

    snapshot = {
        "as_of": now.isoformat(),
        "symbol": ctx.candidate.get("symbol"),
        "action": action,
        "quote_price": ctx.quote.price if ctx.quote else None,
        "buying_power": ctx.cash.buying_power if ctx.cash else None,
        "sellable_quantity": ctx.position.sellable_quantity if ctx.position else 0,
        "orders_today_count": ctx.orders_today_count,
        "gross_order_value_today": ctx.gross_order_value_today,
        "cooldown_remaining_seconds": ctx.cooldown_seconds_remaining,
        "market_open": vn_market_is_open(now),
        "user_mode": ctx.user_mode,
        "reasons": reasons,
        "warnings": warnings,
    }
    return RiskValidationResult(
        status=status, reasons=reasons, warnings=warnings, snapshot=snapshot,
    )
