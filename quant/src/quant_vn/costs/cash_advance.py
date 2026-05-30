"""
Cash advance model for Vietnam brokerage — Ứng trước tiền bán chứng khoán.

Cash advance allows an investor to access pending sell proceeds BEFORE the
normal T+2 settlement date. The broker effectively lends the amount and
charges an interest fee.

Settlement state after a sell trade:
    PENDING  → proceeds are held by broker, awaiting T+2 settlement
    ADVANCED → investor has drawn an advance; liability recorded
    SETTLED  → proceeds fully settled at T+2

Rules enforced by this model:
1. Cash advance is DISABLED by default. Must be explicitly enabled in config.
2. Advance can only be drawn against PENDING (unsettled) sell proceeds.
3. Net cash available = advanced_amount - total_advance_fee.
4. When T+2 settlement arrives, the advance liability is CLOSED — no new cash
   is credited (the advance already credited it on the draw date).
5. Double-counting prevention: pending_cash that is ADVANCED must NOT also
   contribute to settled_cash on settlement date.

Fee formulas:
    Daily interest:
        daily_rate = annualized_rate / day_count_basis   (use 365, not 252)
        fee_before_vat = advanced_amount * daily_rate * advance_days
        fee_before_vat = max(fee_before_vat, minimum_fee)

    Flat fee:
        fee_before_vat = advanced_amount * flat_fee_rate
        fee_before_vat = max(fee_before_vat, minimum_fee)

    VAT on advance fee (if enabled and not already included):
        vat = fee_before_vat * vat_rate

    total_advance_fee = fee_before_vat + vat
    net_advanced_cash = advanced_amount - total_advance_fee

DISCLAIMER: Advance fee rates vary by broker and change over time.
Verify with your broker before configuring this model. For research only.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class FeeModel(str, Enum):
    DAILY_INTEREST = "daily_interest"       # daily_rate * advance_days
    ANNUALIZED_RATE = "annualized_rate"     # annualized / 365 * advance_days
    FLAT_FEE = "flat_fee"                   # flat_fee_rate * amount


@dataclass(frozen=True)
class CashAdvanceResult:
    """Result of a cash advance fee calculation."""
    advanced_amount: float        # VND — amount advanced
    advance_days: int             # number of days until settlement
    fee_model: FeeModel
    daily_rate_used: float        # the daily rate actually applied
    fee_before_vat: float         # VND — fee before VAT
    vat_amount: float             # VND — VAT on advance fee (0 if disabled/included)
    total_advance_fee: float      # VND — fee_before_vat + vat_amount
    net_advanced_cash: float      # VND — advanced_amount - total_advance_fee
    min_fee_applied: bool         # True if minimum fee override was triggered


@dataclass
class CashAdvanceProfile:
    """
    Configuration for a broker's cash advance service.

    Args:
        enabled:            Whether cash advance is available and enabled.
        fee_model:          How the fee is calculated.
        annualized_rate:    Annual interest rate (for ANNUALIZED_RATE model).
        daily_rate:         Per-day interest rate (for DAILY_INTEREST model).
        flat_fee_rate:      Flat percentage of advanced amount (for FLAT_FEE).
        day_count_basis:    Divisor for annualized → daily conversion (default 365).
        minimum_fee:        Minimum fee per advance request (VND).
        fee_includes_vat:   Whether the quoted rate already includes VAT.
        vat_enabled:        Whether VAT applies to the advance fee.
        vat_rate:           VAT rate as decimal (default 0.10 = 10%).
        max_advance_pct:    Maximum fraction of pending sell proceeds advanceable.
    """
    enabled: bool = False
    fee_model: FeeModel = FeeModel.DAILY_INTEREST
    annualized_rate: float | None = None
    daily_rate: float | None = None
    flat_fee_rate: float | None = None
    day_count_basis: int = 365
    minimum_fee: float = 0.0
    fee_includes_vat: bool | None = None   # None = unknown, must be verified
    vat_enabled: bool = True
    vat_rate: float = 0.10
    max_advance_pct: float = 1.0


@dataclass
class CashAdvanceModel:
    """
    Compute cash advance fees and net advanced cash.

    Usage:
        model = CashAdvanceModel(profile)
        result = model.calculate(advanced_amount=45_000_000, advance_days=2)

    Accounting rules enforced:
        1. pending_cash is marked ADVANCED (not doubled in settled_cash later)
        2. Only (advanced_amount - total_fee) enters available cash
        3. On settlement date, advance liability is CLOSED — no new cash added
    """
    profile: CashAdvanceProfile

    def _effective_daily_rate(self) -> float:
        p = self.profile
        if p.fee_model == FeeModel.DAILY_INTEREST:
            if p.daily_rate is None:
                raise ValueError("daily_rate must be set for DAILY_INTEREST model")
            return p.daily_rate
        elif p.fee_model == FeeModel.ANNUALIZED_RATE:
            if p.annualized_rate is None:
                raise ValueError("annualized_rate must be set for ANNUALIZED_RATE model")
            return p.annualized_rate / p.day_count_basis
        elif p.fee_model == FeeModel.FLAT_FEE:
            return 0.0   # daily rate not used for flat fee
        raise ValueError(f"Unknown fee_model: {p.fee_model}")

    def calculate(self, advanced_amount: float, advance_days: int) -> CashAdvanceResult:
        """
        Calculate advance fee and net cash for an advance request.

        Args:
            advanced_amount: VND amount to advance (must be <= pending sell proceeds).
            advance_days:    Number of days until settlement (use calendar days, not
                             trading days, matching typical broker practice).
        """
        if not self.profile.enabled:
            raise ValueError(
                "Cash advance is disabled. Enable it in CashAdvanceProfile before calling calculate()."
            )
        if advanced_amount < 0:
            raise ValueError(f"advanced_amount must be non-negative, got {advanced_amount}")
        if advance_days < 0:
            raise ValueError(f"advance_days must be non-negative, got {advance_days}")

        p = self.profile

        # --- Fee calculation ---
        if p.fee_model == FeeModel.FLAT_FEE:
            if p.flat_fee_rate is None:
                raise ValueError("flat_fee_rate must be set for FLAT_FEE model")
            raw_fee = advanced_amount * p.flat_fee_rate
            daily_rate_used = 0.0
        else:
            daily_rate_used = self._effective_daily_rate()
            raw_fee = advanced_amount * daily_rate_used * advance_days

        fee_before_vat = max(raw_fee, p.minimum_fee)
        min_fee_applied = (p.minimum_fee > 0 and raw_fee < p.minimum_fee)

        # --- VAT on advance fee ---
        if p.fee_includes_vat is True or not p.vat_enabled:
            vat_amount = 0.0
        else:
            vat_amount = fee_before_vat * p.vat_rate

        total_advance_fee = fee_before_vat + vat_amount
        net_advanced_cash = advanced_amount - total_advance_fee

        return CashAdvanceResult(
            advanced_amount=advanced_amount,
            advance_days=advance_days,
            fee_model=p.fee_model,
            daily_rate_used=daily_rate_used if p.fee_model != FeeModel.FLAT_FEE else 0.0,
            fee_before_vat=fee_before_vat,
            vat_amount=vat_amount,
            total_advance_fee=total_advance_fee,
            net_advanced_cash=net_advanced_cash,
            min_fee_applied=min_fee_applied,
        )

    def max_advance_amount(self, pending_sell_proceeds: float) -> float:
        """Maximum VND that can be advanced against pending sell proceeds."""
        return pending_sell_proceeds * self.profile.max_advance_pct


# Disabled profile — used as default (cash advance off unless explicitly configured)
CASH_ADVANCE_DISABLED = CashAdvanceProfile(enabled=False)
