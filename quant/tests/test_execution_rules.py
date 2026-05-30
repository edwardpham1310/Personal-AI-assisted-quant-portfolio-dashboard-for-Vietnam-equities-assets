"""
Tests for execution/rules.py — Pre-trade validation rules.

Tests 7-11 from specification:
    Test 7: Lot size validation
    Test 8: Insufficient cash
    Test 9: Insufficient sellable shares
    Test 10: Liquidity filter
    Test 11: Price limits
"""

import pytest
from quant_vn.execution.rules import (
    RuleViolation,
    check_lot_size,
    check_price_limits,
    check_cash_sufficiency,
    check_sellable_shares,
    check_liquidity,
    run_all_checks,
    LOT_SIZE_VN,
)


class TestLotSize:
    """Test 7: Lot size validation."""

    def test_five_lots_valid(self):
        result = check_lot_size(500, lot_size=100)
        assert result.passed is True

    def test_not_multiple_invalid(self):
        """155 shares with lot=100 → invalid."""
        result = check_lot_size(155, lot_size=100)
        assert result.passed is False
        assert RuleViolation.LOT_SIZE_VIOLATION in result.violations

    def test_round_down_adjustment(self):
        """155 → round down to 100."""
        result = check_lot_size(155, lot_size=100, auto_round_down=True)
        assert result.adjusted_quantity == 100

    def test_zero_quantity_invalid(self):
        result = check_lot_size(0)
        assert result.passed is False
        assert RuleViolation.ZERO_QUANTITY in result.violations

    def test_fifty_shares_odd_lot(self):
        result = check_lot_size(50, lot_size=100)
        assert result.passed is False

    def test_negative_quantity_invalid(self):
        result = check_lot_size(-100, lot_size=100)
        assert result.passed is False

    def test_custom_lot_size_10(self):
        result = check_lot_size(30, lot_size=10)
        assert result.passed is True

    def test_exact_100_valid(self):
        result = check_lot_size(100, lot_size=100)
        assert result.passed is True


class TestPriceLimits:
    """Test 11: Price limit enforcement."""

    def test_hose_at_ceiling_valid(self):
        result = check_price_limits(107_000, reference_price=100_000, exchange="HOSE")
        assert result.passed is True

    def test_hose_above_ceiling_invalid(self):
        """Test 11: Buy price above HOSE ceiling → reject."""
        result = check_price_limits(107_100, reference_price=100_000, exchange="HOSE")
        assert result.passed is False
        assert RuleViolation.PRICE_ABOVE_CEILING in result.violations

    def test_hose_at_floor_valid(self):
        result = check_price_limits(93_000, reference_price=100_000, exchange="HOSE")
        assert result.passed is True

    def test_hose_below_floor_invalid(self):
        result = check_price_limits(92_900, reference_price=100_000, exchange="HOSE")
        assert result.passed is False
        assert RuleViolation.PRICE_BELOW_FLOOR in result.violations

    def test_hnx_10pct_limits(self):
        """HNX limits are ±10%."""
        assert check_price_limits(55_000, 50_000, "HNX").passed is True   # +10%
        assert check_price_limits(55_100, 50_000, "HNX").passed is False  # >+10%
        assert check_price_limits(45_000, 50_000, "HNX").passed is True   # -10%

    def test_upcom_15pct_limits(self):
        """UPCoM limits are ±15%."""
        assert check_price_limits(34_500, 30_000, "UPCOM").passed is True   # +15%
        assert check_price_limits(34_600, 30_000, "UPCOM").passed is False  # >+15%

    def test_missing_reference_price_warn_only(self):
        """Default: warn but allow if reference price missing."""
        result = check_price_limits(100_000, reference_price=None, exchange="HOSE")
        assert result.passed is True
        assert len(result.messages) > 0

    def test_missing_reference_price_reject_if_strict(self):
        result = check_price_limits(
            100_000, reference_price=None, exchange="HOSE", reject_if_missing=True
        )
        assert result.passed is False
        assert RuleViolation.MISSING_REFERENCE_PRICE in result.violations

    def test_unknown_exchange(self):
        result = check_price_limits(100_000, 100_000, "INVALID")
        assert result.passed is False
        assert RuleViolation.UNKNOWN_EXCHANGE in result.violations


class TestCashSufficiency:
    """Test 8: Insufficient cash."""

    def test_sufficient_cash(self):
        result = check_cash_sufficiency(required_cash=10_000_000, settled_cash=15_000_000)
        assert result.passed is True

    def test_exact_cash(self):
        result = check_cash_sufficiency(required_cash=10_000_000, settled_cash=10_000_000)
        assert result.passed is True

    def test_insufficient_cash(self):
        """Test 8: Cash 50M, required > 50M → reject."""
        result = check_cash_sufficiency(required_cash=50_075_000, settled_cash=50_000_000)
        assert result.passed is False
        assert RuleViolation.INSUFFICIENT_CASH in result.violations

    def test_pending_cash_does_not_satisfy(self):
        """Pending cash not in settled_cash → check fails (settled = 0)."""
        result = check_cash_sufficiency(required_cash=10_000_000, settled_cash=0)
        assert result.passed is False

    def test_negative_required_raises(self):
        result = check_cash_sufficiency(required_cash=-1_000, settled_cash=10_000_000)
        assert result.passed is False
        assert RuleViolation.NEGATIVE_VALUE in result.violations


class TestSellableShares:
    """Test 9: Insufficient sellable shares."""

    def test_sufficient_settled_shares(self):
        result = check_sellable_shares("FPT", requested_quantity=500, settled_shares=1000)
        assert result.passed is True

    def test_exact_shares(self):
        result = check_sellable_shares("FPT", requested_quantity=1000, settled_shares=1000)
        assert result.passed is True

    def test_insufficient_shares(self):
        """Test 9: 0 settled shares (1000 pending) → reject sell of 1000."""
        result = check_sellable_shares("FPT", requested_quantity=1000, settled_shares=0)
        assert result.passed is False
        assert RuleViolation.INSUFFICIENT_SHARES in result.violations

    def test_zero_quantity_invalid(self):
        result = check_sellable_shares("FPT", requested_quantity=0, settled_shares=1000)
        assert result.passed is False
        assert RuleViolation.ZERO_QUANTITY in result.violations


class TestLiquidity:
    """Test 10: Liquidity filter."""

    def test_order_4pct_adv_valid(self):
        """4% of ADV → valid (below 5% threshold)."""
        result = check_liquidity(
            order_value_vnd=2_000_000_000,
            avg_daily_value_20d_vnd=50_000_000_000,
            max_order_adv_pct=0.05,
        )
        assert result.passed is True

    def test_order_at_5pct_threshold(self):
        result = check_liquidity(
            order_value_vnd=2_500_000_000,
            avg_daily_value_20d_vnd=50_000_000_000,
            max_order_adv_pct=0.05,
        )
        assert result.passed is True

    def test_order_6pct_adv_invalid(self):
        """Test 10: 6% of ADV → exceeds 5% limit."""
        result = check_liquidity(
            order_value_vnd=3_000_000_000,
            avg_daily_value_20d_vnd=50_000_000_000,
            max_order_adv_pct=0.05,
        )
        assert result.passed is False
        assert RuleViolation.LIQUIDITY_LIMIT_EXCEEDED in result.violations

    def test_illiquid_stock_below_min(self):
        """avg_value_20d below 5B threshold → fail."""
        result = check_liquidity(
            order_value_vnd=10_000_000,
            avg_daily_value_20d_vnd=3_000_000_000,
            min_avg_daily_value_vnd=5_000_000_000,
        )
        assert result.passed is False

    def test_missing_liquidity_data(self):
        result = check_liquidity(
            order_value_vnd=10_000_000,
            avg_daily_value_20d_vnd=None,
        )
        assert result.passed is False
        assert RuleViolation.MISSING_LIQUIDITY_DATA in result.violations


class TestRunAllChecks:
    def test_valid_buy_passes_all(self):
        result = run_all_checks(
            order_type="buy",
            symbol="FPT",
            quantity=1000,
            order_price=86_000,
            reference_price=85_000,
            exchange="HOSE",
            settled_cash=100_000_000,
            required_cash=86_500_000,
            avg_daily_value_20d_vnd=50_000_000_000,
        )
        assert result.passed is True

    def test_buy_with_lot_violation_fails(self):
        result = run_all_checks(
            order_type="buy",
            symbol="FPT",
            quantity=155,
            order_price=86_000,
            reference_price=85_000,
            exchange="HOSE",
            settled_cash=100_000_000,
            required_cash=13_400_000,
            avg_daily_value_20d_vnd=50_000_000_000,
        )
        assert result.passed is False
        assert RuleViolation.LOT_SIZE_VIOLATION in result.violations

    def test_buy_with_insufficient_cash_fails(self):
        result = run_all_checks(
            order_type="buy",
            symbol="FPT",
            quantity=1000,
            order_price=86_000,
            reference_price=85_000,
            exchange="HOSE",
            settled_cash=10_000_000,   # insufficient
            required_cash=86_500_000,
            avg_daily_value_20d_vnd=50_000_000_000,
        )
        assert result.passed is False
        assert RuleViolation.INSUFFICIENT_CASH in result.violations
