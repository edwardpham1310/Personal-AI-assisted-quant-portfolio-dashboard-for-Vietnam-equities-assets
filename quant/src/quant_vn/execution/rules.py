"""
Pre-trade execution validation rules for Vietnam stock market.

All checks return RuleCheckResult. A check result with passed=True means the
order can proceed. Multiple checks can be run individually or via run_all_checks().

Vietnam market rules encoded here:
    - Lot size: minimum 100 shares per order on HOSE/HNX board lot market.
    - Price limits: HOSE ±7%, HNX ±10%, UPCoM ±15% from reference (prev close).
    - Cash sufficiency: only SETTLED cash counts (not pending sell proceeds).
    - Sellable shares: only SETTLED shares count (not pending buy deliveries).
    - Liquidity: order size must not exceed max_order_adv_pct of 20-day ADV.

These rules run BEFORE cash is committed or positions are changed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class RuleViolation(str, Enum):
    LOT_SIZE_VIOLATION = "lot_size_violation"
    PRICE_ABOVE_CEILING = "price_above_ceiling"
    PRICE_BELOW_FLOOR = "price_below_floor"
    MISSING_REFERENCE_PRICE = "missing_reference_price"
    UNKNOWN_EXCHANGE = "unknown_exchange"
    INSUFFICIENT_CASH = "insufficient_cash"
    INSUFFICIENT_SHARES = "insufficient_shares"
    LIQUIDITY_LIMIT_EXCEEDED = "liquidity_limit_exceeded"
    MISSING_LIQUIDITY_DATA = "missing_liquidity_data"
    ZERO_QUANTITY = "zero_quantity"
    NEGATIVE_VALUE = "negative_value"


# Standard board lot for HOSE and HNX
LOT_SIZE_VN: int = 100

# Daily price limit percentages by exchange
PRICE_LIMIT_PCT: dict[str, float] = {
    "HOSE": 0.07,
    "HSX": 0.07,   # alias
    "HNX": 0.10,
    "UPCOM": 0.15,
    "UPCOM_UPC": 0.15,  # alias
}


@dataclass
class RuleCheckResult:
    """Result of one or more pre-trade rule checks."""
    passed: bool
    violations: list[RuleViolation] = field(default_factory=list)
    messages: list[str] = field(default_factory=list)
    adjusted_quantity: int | None = None   # for lot-size auto-round-down

    def merge(self, other: "RuleCheckResult") -> "RuleCheckResult":
        """Combine two results (both must pass for result to pass)."""
        return RuleCheckResult(
            passed=self.passed and other.passed,
            violations=self.violations + other.violations,
            messages=self.messages + other.messages,
            adjusted_quantity=other.adjusted_quantity or self.adjusted_quantity,
        )


def check_lot_size(
    quantity: int | float,
    lot_size: int = LOT_SIZE_VN,
    auto_round_down: bool = True,
) -> RuleCheckResult:
    """
    Validate that ``quantity`` is a non-zero multiple of ``lot_size``.

    Vietnam HOSE/HNX board lot = 100 shares. Fractional or non-lot-aligned
    orders are rejected on the main board.

    Args:
        quantity:        Number of shares requested.
        lot_size:        Minimum and granularity (default 100).
        auto_round_down: If True and quantity is not a multiple, include
                         adjusted_quantity (rounded down) in the result.
                         The order is still marked as failed unless the caller
                         decides to use adjusted_quantity.
    """
    # Detect fractional float quantity (e.g. 100.5) — never legal in Vietnam.
    if isinstance(quantity, float) and quantity != int(quantity):
        return RuleCheckResult(
            passed=False,
            violations=[RuleViolation.LOT_SIZE_VIOLATION],
            messages=[
                f"Fractional quantity {quantity} is not allowed in Vietnam market. "
                f"Use whole shares only."
            ],
        )

    qty = int(quantity)

    if qty <= 0:
        return RuleCheckResult(
            passed=False,
            violations=[RuleViolation.ZERO_QUANTITY],
            messages=[f"Quantity must be positive; got {qty}."],
        )

    if qty % lot_size != 0:
        rounded = (qty // lot_size) * lot_size
        adjusted = rounded if auto_round_down and rounded > 0 else None
        return RuleCheckResult(
            passed=False,
            violations=[RuleViolation.LOT_SIZE_VIOLATION],
            messages=[
                f"Quantity {qty} is not a multiple of lot size {lot_size}. "
                f"Nearest valid quantity (round-down): {rounded}."
            ],
            adjusted_quantity=adjusted,
        )

    return RuleCheckResult(passed=True)


def check_price_limits(
    order_price: float,
    reference_price: float | None,
    exchange: str = "HOSE",
    reject_if_missing: bool = False,
) -> RuleCheckResult:
    """
    Check that ``order_price`` is within the daily price band.

    Limits:
        HOSE / HSX: ±7%
        HNX:        ±10%
        UPCoM:      ±15%

    Args:
        order_price:       Proposed execution price (VND).
        reference_price:   Previous session close / reference price (VND).
                           None = missing data.
        exchange:          Exchange code (case-insensitive).
        reject_if_missing: If True and reference_price is None, mark as failed.
                           If False (default), return passed=True with a warning.
    """
    exchange_upper = exchange.upper()
    limit_pct = PRICE_LIMIT_PCT.get(exchange_upper)

    if limit_pct is None:
        return RuleCheckResult(
            passed=False,
            violations=[RuleViolation.UNKNOWN_EXCHANGE],
            messages=[f"Unknown exchange: {exchange!r}. Expected one of {list(PRICE_LIMIT_PCT)}."],
        )

    if reference_price is None:
        if reject_if_missing:
            return RuleCheckResult(
                passed=False,
                violations=[RuleViolation.MISSING_REFERENCE_PRICE],
                messages=["Reference price is missing; cannot check price limits."],
            )
        return RuleCheckResult(
            passed=True,
            messages=["Reference price missing; price limit check skipped."],
        )

    if reference_price <= 0:
        return RuleCheckResult(
            passed=True,
            messages=["Reference price is zero or negative; price limit check skipped."],
        )

    ceiling = reference_price * (1.0 + limit_pct)
    floor = reference_price * (1.0 - limit_pct)

    if order_price > ceiling + 1e-6:
        return RuleCheckResult(
            passed=False,
            violations=[RuleViolation.PRICE_ABOVE_CEILING],
            messages=[
                f"Order price {order_price:,.0f} VND exceeds {exchange_upper} ceiling "
                f"{ceiling:,.0f} VND (ref {reference_price:,.0f} × +{limit_pct*100:.0f}%)."
            ],
        )

    if order_price < floor - 1e-6:
        return RuleCheckResult(
            passed=False,
            violations=[RuleViolation.PRICE_BELOW_FLOOR],
            messages=[
                f"Order price {order_price:,.0f} VND is below {exchange_upper} floor "
                f"{floor:,.0f} VND (ref {reference_price:,.0f} × -{limit_pct*100:.0f}%)."
            ],
        )

    return RuleCheckResult(passed=True)


def check_cash_sufficiency(
    required_cash: float,
    settled_cash: float,
    tolerance: float = 1.0,
) -> RuleCheckResult:
    """
    Check that settled_cash >= required_cash (within tolerance VND).

    IMPORTANT: Only SETTLED cash counts. Pending sell proceeds (unsettled)
    do NOT satisfy this check — they require a cash advance (see
    recommendation/validator.py).

    Args:
        required_cash:  Total cash needed (notional + all buy-side costs).
        settled_cash:   Cash currently settled and available.
        tolerance:      VND rounding tolerance (default 1 VND).
    """
    if required_cash < 0:
        return RuleCheckResult(
            passed=False,
            violations=[RuleViolation.NEGATIVE_VALUE],
            messages=[f"required_cash must be non-negative; got {required_cash:,.0f}."],
        )

    if settled_cash + tolerance >= required_cash:
        return RuleCheckResult(passed=True)

    shortfall = required_cash - settled_cash
    return RuleCheckResult(
        passed=False,
        violations=[RuleViolation.INSUFFICIENT_CASH],
        messages=[
            f"Insufficient settled cash. Required: {required_cash:,.0f} VND, "
            f"Available: {settled_cash:,.0f} VND, "
            f"Shortfall: {shortfall:,.0f} VND. "
            f"Pending sell proceeds (if any) require cash advance service."
        ],
    )


def check_sellable_shares(
    symbol: str,
    requested_quantity: int,
    settled_shares: int,
) -> RuleCheckResult:
    """
    Check that enough SETTLED shares exist to cover the sell order.

    IMPORTANT: Pending shares (bought but not yet at T+2) do NOT count.
    Selling pending shares is not allowed by default.

    Args:
        symbol:             Stock ticker for error messages.
        requested_quantity: Number of shares to sell.
        settled_shares:     Settled shares currently available.
    """
    if requested_quantity <= 0:
        return RuleCheckResult(
            passed=False,
            violations=[RuleViolation.ZERO_QUANTITY],
            messages=[f"Sell quantity must be positive; got {requested_quantity}."],
        )

    if settled_shares >= requested_quantity:
        return RuleCheckResult(passed=True)

    return RuleCheckResult(
        passed=False,
        violations=[RuleViolation.INSUFFICIENT_SHARES],
        messages=[
            f"Insufficient settled shares of {symbol}. "
            f"Requested: {requested_quantity}, Settled: {settled_shares}. "
            f"Shares from recent buys may still be pending settlement (T+2 rule)."
        ],
    )


def check_liquidity(
    order_value_vnd: float,
    avg_daily_value_20d_vnd: float | None,
    max_order_adv_pct: float = 0.05,
    min_avg_daily_value_vnd: float = 5_000_000_000.0,
) -> RuleCheckResult:
    """
    Check that the order size is within liquidity constraints.

    Rules:
        1. avg_daily_value_20d >= min_avg_daily_value_vnd (stock is liquid enough)
        2. order_value <= avg_daily_value_20d * max_order_adv_pct (order not too large)

    Args:
        order_value_vnd:           VND value of proposed order.
        avg_daily_value_20d_vnd:   20-day average daily value in VND. None = missing.
        max_order_adv_pct:         Maximum fraction of ADV per order (default 5%).
        min_avg_daily_value_vnd:   Minimum ADV required to consider stock tradable.
    """
    if avg_daily_value_20d_vnd is None:
        return RuleCheckResult(
            passed=False,
            violations=[RuleViolation.MISSING_LIQUIDITY_DATA],
            messages=["avg_daily_value_20d is missing; liquidity check cannot be performed."],
        )

    messages: list[str] = []
    violations: list[RuleViolation] = []

    if avg_daily_value_20d_vnd < min_avg_daily_value_vnd:
        violations.append(RuleViolation.LIQUIDITY_LIMIT_EXCEEDED)
        messages.append(
            f"Stock avg daily value {avg_daily_value_20d_vnd/1e9:.2f}B VND is below "
            f"minimum threshold {min_avg_daily_value_vnd/1e9:.2f}B VND."
        )

    if avg_daily_value_20d_vnd > 0:
        participation = order_value_vnd / avg_daily_value_20d_vnd
        if participation > max_order_adv_pct + 1e-9:
            violations.append(RuleViolation.LIQUIDITY_LIMIT_EXCEEDED)
            messages.append(
                f"Order value {order_value_vnd/1e6:.1f}M VND is {participation*100:.2f}% of "
                f"20-day ADV {avg_daily_value_20d_vnd/1e9:.2f}B VND — exceeds limit of "
                f"{max_order_adv_pct*100:.1f}%."
            )

    if violations:
        return RuleCheckResult(passed=False, violations=violations, messages=messages)
    return RuleCheckResult(passed=True)


def run_all_checks(
    order_type: str,            # "buy" or "sell"
    symbol: str,
    quantity: int,
    order_price: float,
    reference_price: float | None = None,
    exchange: str = "HOSE",
    settled_cash: float = 0.0,
    required_cash: float = 0.0,
    settled_shares: int = 0,
    avg_daily_value_20d_vnd: float | None = None,
    max_order_adv_pct: float = 0.05,
    min_avg_daily_value_vnd: float = 5_000_000_000.0,
    lot_size: int = LOT_SIZE_VN,
    enforce_price_limits: bool = True,
    enforce_liquidity: bool = True,
    reject_if_missing_price_limit: bool = False,
) -> RuleCheckResult:
    """
    Run all applicable pre-trade checks and aggregate results.

    Returns a single RuleCheckResult. violations list is ordered by check sequence.
    """
    result = RuleCheckResult(passed=True)

    # Lot size check (applies to both buy and sell)
    result = result.merge(check_lot_size(quantity, lot_size))

    # Price limits (optional; requires reference price data)
    if enforce_price_limits:
        result = result.merge(check_price_limits(
            order_price, reference_price, exchange, reject_if_missing_price_limit
        ))

    if order_type.lower() == "buy":
        # Cash sufficiency
        result = result.merge(check_cash_sufficiency(required_cash, settled_cash))

    elif order_type.lower() == "sell":
        # Sellable shares
        result = result.merge(check_sellable_shares(symbol, quantity, settled_shares))

    # Liquidity (optional)
    if enforce_liquidity:
        order_value = order_price * quantity
        result = result.merge(check_liquidity(
            order_value, avg_daily_value_20d_vnd, max_order_adv_pct, min_avg_daily_value_vnd
        ))

    return result
