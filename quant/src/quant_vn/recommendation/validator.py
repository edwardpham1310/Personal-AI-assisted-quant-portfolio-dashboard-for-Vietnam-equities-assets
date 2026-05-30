"""
Recommendation validator for Vietnam stock market.

Validates BUY and SELL recommendations before they are shown to the user.
Rejects or warns on impossible trades, settlement conflicts, insufficient
cash/shares, lot size violations, price limit breaches, and liquidity issues.

BUY validation rules:
    1. Symbol passes liquidity filter (avg_value_20d >= threshold).
    2. Order value <= avg_value_20d * max_order_adv_pct.
    3. quantity is a valid lot size multiple.
    4. order_price is within ceiling/floor (if reference price available).
    5. total_cash_required (notional + fees) <= available settled_cash.
       If settled_cash is insufficient but pending_cash exists:
           - If allow_auto_advance=False: WARN (rejected unless cash advance is used).
           - If allow_auto_advance=True: compute advance cost and include in output.

SELL validation rules:
    1. settled_shares >= requested quantity.
    2. quantity is a valid lot size multiple.
    3. order_price within ceiling/floor.
    4. Output shows net pending proceeds and settlement date.
    5. Cash advance option shown if advance is enabled and configured.

DISCLAIMER: This validator is for research purposes only and does not constitute
financial advice. All recommendations are informational only.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from ..execution.rules import (
    RuleCheckResult,
    check_lot_size,
    check_price_limits,
    check_cash_sufficiency,
    check_sellable_shares,
    check_liquidity,
    LOT_SIZE_VN,
)
from ..costs.transaction import TransactionCostModel, DEFAULT_COSTS
from ..costs.cash_advance import CashAdvanceModel
from ..market.calendar import t2_settlement_date


class ValidationSeverity(str, Enum):
    ERROR = "error"      # recommendation must be suppressed
    WARNING = "warning"  # recommendation may proceed with caveat
    INFO = "info"


@dataclass(frozen=True)
class ValidationIssue:
    code: str
    severity: ValidationSeverity
    message: str


@dataclass
class RecommendationPayload:
    """Input to the validator — describes a proposed BUY or SELL recommendation."""
    action: str                          # "BUY" or "SELL"
    symbol: str
    quantity: int
    price: float                         # proposed execution price
    trade_date: datetime.date

    # Portfolio state (required for validation)
    settled_cash: float = 0.0
    pending_cash: float = 0.0
    settled_shares: dict[str, int] = field(default_factory=dict)
    pending_shares: dict[str, int] = field(default_factory=dict)

    # Market context
    reference_price: float | None = None    # for price limit check
    exchange: str = "HOSE"
    avg_daily_value_20d: float | None = None

    # Config
    lot_size: int = LOT_SIZE_VN
    max_order_adv_pct: float = 0.05
    min_avg_daily_value_vnd: float = 5_000_000_000.0
    enforce_price_limits: bool = True
    reject_if_missing_price_limit: bool = False
    allow_auto_advance_for_buying_power: bool = False


@dataclass
class ValidationResult:
    """Result of validating a recommendation payload."""
    payload: RecommendationPayload
    issues: list[ValidationIssue] = field(default_factory=list)
    approved: bool = True

    # Cost breakdown (populated for approved BUY)
    brokerage_fee: float = 0.0
    vat_amount: float = 0.0
    sell_tax: float = 0.0
    slippage_cost: float = 0.0
    total_cost: float = 0.0
    total_cash_required: float = 0.0      # for BUY: notional + total_cost
    net_proceeds: float = 0.0             # for SELL: notional - total_cost
    settlement_date: datetime.date | None = None
    estimated_advance_amount: float = 0.0
    estimated_advance_fee: float = 0.0
    estimated_advance_vat: float = 0.0
    estimated_net_advance_cash: float = 0.0

    @property
    def errors(self) -> list[ValidationIssue]:
        return [i for i in self.issues if i.severity == ValidationSeverity.ERROR]

    @property
    def warnings(self) -> list[ValidationIssue]:
        return [i for i in self.issues if i.severity == ValidationSeverity.WARNING]

    def add_error(self, code: str, message: str) -> None:
        self.issues.append(ValidationIssue(code, ValidationSeverity.ERROR, message))
        self.approved = False

    def add_warning(self, code: str, message: str) -> None:
        self.issues.append(ValidationIssue(code, ValidationSeverity.WARNING, message))

    def summary(self) -> str:
        status = "APPROVED" if self.approved else "REJECTED"
        errors = len(self.errors)
        warnings = len(self.warnings)
        return (
            f"[{status}] {self.payload.action} {self.payload.quantity} "
            f"{self.payload.symbol} @ {self.payload.price:,.0f} VND — "
            f"{errors} errors, {warnings} warnings"
        )


class RecommendationValidator:
    """
    Stateless recommendation validator.

    Each check is a separate method, independently testable.
    Call validate(payload) to run all applicable checks.
    """

    def __init__(
        self,
        cost_model: TransactionCostModel | None = None,
        cash_advance_model: CashAdvanceModel | None = None,
        max_stale_hours: float = 24.0,
    ) -> None:
        self._cost_model = cost_model or DEFAULT_COSTS
        self._advance_model = cash_advance_model
        self._max_stale_hours = max_stale_hours

    def validate(self, payload: RecommendationPayload) -> ValidationResult:
        """Run all applicable checks for the given action."""
        result = ValidationResult(payload=payload)

        if payload.action.upper() not in ("BUY", "SELL"):
            result.add_error(
                "UNKNOWN_ACTION",
                f"Unknown action {payload.action!r}. Expected 'BUY' or 'SELL'.",
            )
            return result

        if payload.action.upper() == "BUY":
            self._validate_buy(payload, result)
        else:
            self._validate_sell(payload, result)

        return result

    # ── BUY validation ───────────────────────────────────────────────────────

    def _validate_buy(self, payload: RecommendationPayload, result: ValidationResult) -> None:
        # Lot size
        lot_check = check_lot_size(payload.quantity, payload.lot_size)
        if not lot_check.passed:
            for msg in lot_check.messages:
                result.add_error("LOT_SIZE", msg)

        # Price limits
        if payload.enforce_price_limits:
            price_check = check_price_limits(
                payload.price, payload.reference_price,
                payload.exchange, payload.reject_if_missing_price_limit,
            )
            if not price_check.passed:
                for msg in price_check.messages:
                    result.add_error("PRICE_LIMIT", msg)
            elif price_check.messages:
                for msg in price_check.messages:
                    result.add_warning("PRICE_LIMIT_WARN", msg)

        # Liquidity
        if payload.avg_daily_value_20d is not None:
            order_value = payload.price * payload.quantity
            liq_check = check_liquidity(
                order_value, payload.avg_daily_value_20d,
                payload.max_order_adv_pct, payload.min_avg_daily_value_vnd,
            )
            if not liq_check.passed:
                for msg in liq_check.messages:
                    result.add_warning("LIQUIDITY", msg)
        else:
            result.add_warning("LIQUIDITY_MISSING", "avg_daily_value_20d is missing; liquidity check skipped.")

        # Cost calculation
        notional = payload.price * payload.quantity
        cost_bd = self._cost_model.buy_cost(
            notional=notional,
            quantity=payload.quantity,
            price=payload.price,
        )
        total_required = notional + cost_bd.total_cost

        result.brokerage_fee = cost_bd.brokerage_fee
        result.vat_amount = cost_bd.vat_amount
        result.slippage_cost = cost_bd.slippage_cost
        result.total_cost = cost_bd.total_cost
        result.total_cash_required = total_required
        result.settlement_date = t2_settlement_date(payload.trade_date)

        # Cash sufficiency
        cash_check = check_cash_sufficiency(total_required, payload.settled_cash)
        if not cash_check.passed:
            shortfall = total_required - payload.settled_cash
            if payload.pending_cash > 0:
                if payload.allow_auto_advance_for_buying_power and self._advance_model is not None:
                    # Attempt to cover shortfall via cash advance.
                    # advance_days = calendar days between trade_date and T+2 settlement
                    # (e.g. Fri trade → Tue settle = 4 calendar days, not 2).
                    settlement = t2_settlement_date(payload.trade_date)
                    advance_days_calc = max(1, (settlement - payload.trade_date).days)
                    advance_amount = min(shortfall, payload.pending_cash)
                    try:
                        adv_result = self._advance_model.calculate(advance_amount, advance_days=advance_days_calc)
                        combined = payload.settled_cash + adv_result.net_advanced_cash
                        # Always populate advance estimate fields for transparency
                        result.estimated_advance_amount = advance_amount
                        result.estimated_advance_fee = adv_result.fee_before_vat
                        result.estimated_advance_vat = adv_result.vat_amount
                        result.estimated_net_advance_cash = adv_result.net_advanced_cash
                        if combined >= total_required - 1.0:
                            result.add_warning(
                                "CASH_ADVANCE_REQUIRED",
                                f"Settled cash {payload.settled_cash:,.0f} VND is insufficient. "
                                f"Cash advance of {advance_amount:,.0f} VND required "
                                f"(fee: {adv_result.total_advance_fee:,.0f} VND). "
                                f"Enable cash advance with your broker before trading.",
                            )
                        else:
                            result.add_warning(
                                "CASH_ADVANCE_REQUIRED",
                                f"Settled cash {payload.settled_cash:,.0f} VND insufficient; "
                                f"advance of {advance_amount:,.0f} VND would net "
                                f"{adv_result.net_advanced_cash:,.0f} VND but still leaves a shortfall.",
                            )
                            result.add_error(
                                "INSUFFICIENT_CASH",
                                f"Even with full cash advance, total available cash "
                                f"({combined:,.0f} VND) is less than required "
                                f"({total_required:,.0f} VND).",
                            )
                    except Exception as exc:
                        result.add_error("CASH_ADVANCE_ERROR", str(exc))
                else:
                    result.add_warning(
                        "PENDING_CASH_EXISTS",
                        f"Insufficient settled cash ({payload.settled_cash:,.0f} VND). "
                        f"Pending sell proceeds of {payload.pending_cash:,.0f} VND exist "
                        f"but require cash advance service (ứng trước tiền bán) before "
                        f"settlement. Cash advance is currently disabled.",
                    )
                    result.add_error(
                        "INSUFFICIENT_SETTLED_CASH",
                        f"Total required: {total_required:,.0f} VND, "
                        f"Settled cash: {payload.settled_cash:,.0f} VND.",
                    )
            else:
                for msg in cash_check.messages:
                    result.add_error("INSUFFICIENT_CASH", msg)

    # ── SELL validation ──────────────────────────────────────────────────────

    def _validate_sell(self, payload: RecommendationPayload, result: ValidationResult) -> None:
        # Lot size
        lot_check = check_lot_size(payload.quantity, payload.lot_size)
        if not lot_check.passed:
            for msg in lot_check.messages:
                result.add_error("LOT_SIZE", msg)

        # Price limits
        if payload.enforce_price_limits:
            price_check = check_price_limits(
                payload.price, payload.reference_price,
                payload.exchange, payload.reject_if_missing_price_limit,
            )
            if not price_check.passed:
                for msg in price_check.messages:
                    result.add_error("PRICE_LIMIT", msg)

        # Sellable shares
        settled = payload.settled_shares.get(payload.symbol, 0)
        share_check = check_sellable_shares(payload.symbol, payload.quantity, settled)
        if not share_check.passed:
            pending = payload.pending_shares.get(payload.symbol, 0)
            if pending > 0:
                result.add_error(
                    "SHARES_PENDING_SETTLEMENT",
                    f"Settled shares of {payload.symbol}: {settled}. "
                    f"Pending (not yet T+2): {pending}. "
                    f"Cannot sell pending shares before settlement.",
                )
            else:
                for msg in share_check.messages:
                    result.add_error("INSUFFICIENT_SHARES", msg)

        # Liquidity check (mirror of buy-side: large sell orders also have market impact)
        if payload.avg_daily_value_20d is not None:
            order_value = payload.price * payload.quantity
            liq_check = check_liquidity(
                order_value, payload.avg_daily_value_20d,
                payload.max_order_adv_pct, payload.min_avg_daily_value_vnd,
            )
            if not liq_check.passed:
                for msg in liq_check.messages:
                    result.add_warning("LIQUIDITY", msg)

        # Cost calculation
        notional = payload.price * payload.quantity
        cost_bd = self._cost_model.sell_cost(
            notional=notional,
            quantity=payload.quantity,
            price=payload.price,
        )
        net_proceeds = notional - cost_bd.total_cost

        result.brokerage_fee = cost_bd.brokerage_fee
        result.vat_amount = cost_bd.vat_amount
        result.sell_tax = cost_bd.sell_tax
        result.slippage_cost = cost_bd.slippage_cost
        result.total_cost = cost_bd.total_cost
        result.net_proceeds = net_proceeds
        result.settlement_date = t2_settlement_date(payload.trade_date)

        # Inform about pending cash and advance option
        if result.approved:
            result.add_warning(
                "PROCEEDS_PENDING",
                f"Net sell proceeds of {net_proceeds:,.0f} VND will be PENDING until "
                f"settlement on {result.settlement_date} (T+2 trading days). "
                f"Cash is NOT available for new buys until then, unless cash advance is used.",
            )
            if self._advance_model is not None and self._advance_model.profile.enabled:
                try:
                    # Actual advance term = calendar days between trade and T+2 settlement
                    settlement = result.settlement_date
                    advance_days_calc = max(1, (settlement - payload.trade_date).days)
                    adv = self._advance_model.calculate(net_proceeds, advance_days=advance_days_calc)
                    result.add_warning(
                        "CASH_ADVANCE_AVAILABLE",
                        f"Cash advance option: receive {adv.net_advanced_cash:,.0f} VND now "
                        f"(fee: {adv.total_advance_fee:,.0f} VND) instead of waiting for T+2.",
                    )
                    result.estimated_advance_amount = net_proceeds
                    result.estimated_advance_fee = adv.fee_before_vat
                    result.estimated_advance_vat = adv.vat_amount
                    result.estimated_net_advance_cash = adv.net_advanced_cash
                except Exception:
                    pass
