"""Tests for costs/cash_advance.py — Cash advance / ứng trước tiền bán."""

import pytest
from quant_vn.costs.cash_advance import (
    CashAdvanceProfile, CashAdvanceModel, FeeModel, CASH_ADVANCE_DISABLED,
)


def _daily_model(daily_rate=0.0003, min_fee=0, vat_enabled=False, fee_includes_vat=False, vat_rate=0.10):
    profile = CashAdvanceProfile(
        enabled=True,
        fee_model=FeeModel.DAILY_INTEREST,
        daily_rate=daily_rate,
        minimum_fee=min_fee,
        vat_enabled=vat_enabled,
        fee_includes_vat=fee_includes_vat,
        vat_rate=vat_rate,
    )
    return CashAdvanceModel(profile=profile)


class TestDailyInterestModel:
    def test_standard_two_days(self):
        """Test 1 (formula): 100M * 0.03% * 2 days = 60,000 VND fee."""
        model = _daily_model(daily_rate=0.0003)
        result = model.calculate(100_000_000, advance_days=2)
        assert result.fee_before_vat == pytest.approx(60_000, abs=1)
        assert result.vat_amount == 0.0
        assert result.total_advance_fee == pytest.approx(60_000, abs=1)
        assert result.net_advanced_cash == pytest.approx(99_940_000, abs=1)

    def test_vat_on_advance_fee(self):
        """VAT enabled, fee does NOT include VAT → vat = fee * rate."""
        model = _daily_model(daily_rate=0.0003, vat_enabled=True, fee_includes_vat=False, vat_rate=0.10)
        result = model.calculate(100_000_000, advance_days=2)
        assert result.fee_before_vat == pytest.approx(60_000, abs=1)
        assert result.vat_amount == pytest.approx(6_000, abs=1)
        assert result.total_advance_fee == pytest.approx(66_000, abs=1)
        assert result.net_advanced_cash == pytest.approx(99_934_000, abs=1)

    def test_vat_already_included_no_double_count(self):
        """fee_includes_vat=True → vat = 0 (double-count prevention)."""
        model = _daily_model(daily_rate=0.0003, vat_enabled=True, fee_includes_vat=True, vat_rate=0.10)
        result = model.calculate(100_000_000, advance_days=2)
        assert result.vat_amount == 0.0
        assert result.total_advance_fee == pytest.approx(60_000, abs=1)

    def test_minimum_fee_override(self):
        """Computed fee < minimum → minimum is applied."""
        model = _daily_model(daily_rate=0.0001, min_fee=50_000)
        result = model.calculate(10_000_000, advance_days=1)
        # computed = 10M * 0.01% * 1 = 1000 < 50000
        assert result.fee_before_vat == pytest.approx(50_000, abs=1)
        assert result.min_fee_applied is True

    def test_minimum_fee_not_applied_when_not_needed(self):
        model = _daily_model(daily_rate=0.0003, min_fee=10_000)
        result = model.calculate(100_000_000, advance_days=2)
        # computed = 60000 > 10000
        assert result.min_fee_applied is False

    def test_zero_advance_days(self):
        """Zero advance days → fee = 0 (or minimum)."""
        model = _daily_model(daily_rate=0.0003, min_fee=0)
        result = model.calculate(100_000_000, advance_days=0)
        assert result.fee_before_vat == 0.0

    def test_net_advanced_cash_formula(self):
        """net_advanced_cash = advanced_amount - total_advance_fee."""
        model = _daily_model(daily_rate=0.0003, vat_enabled=True, fee_includes_vat=False)
        result = model.calculate(100_000_000, advance_days=2)
        expected = result.advanced_amount - result.total_advance_fee
        assert result.net_advanced_cash == pytest.approx(expected, abs=1)

    def test_disabled_raises(self):
        """Disabled model must raise, not silently return 0."""
        model = CashAdvanceModel(profile=CASH_ADVANCE_DISABLED)
        with pytest.raises(ValueError, match="disabled"):
            model.calculate(50_000_000, advance_days=2)


class TestAnnualizedRateModel:
    def test_annualized_uses_365_not_252(self):
        """Critical regression: annualized / 365, NOT annualized / 252."""
        profile = CashAdvanceProfile(
            enabled=True,
            fee_model=FeeModel.ANNUALIZED_RATE,
            annualized_rate=0.365,    # 0.365/365 = 0.001/day
            day_count_basis=365,
            minimum_fee=0,
            vat_enabled=False,
        )
        model = CashAdvanceModel(profile=profile)
        result = model.calculate(1_000_000, advance_days=1)
        # Expected: 1M * (0.365/365) * 1 = 1000 VND
        assert result.fee_before_vat == pytest.approx(1_000, abs=1)

    def test_annualized_rate_missing_raises(self):
        profile = CashAdvanceProfile(
            enabled=True,
            fee_model=FeeModel.ANNUALIZED_RATE,
            annualized_rate=None,
        )
        model = CashAdvanceModel(profile=profile)
        with pytest.raises(ValueError):
            model.calculate(100_000_000, advance_days=2)


class TestFlatFeeModel:
    def test_flat_fee_ignores_days(self):
        """Flat fee is amount * flat_fee_rate, days do not matter."""
        profile = CashAdvanceProfile(
            enabled=True,
            fee_model=FeeModel.FLAT_FEE,
            flat_fee_rate=0.002,
            minimum_fee=0,
            vat_enabled=False,
        )
        model = CashAdvanceModel(profile=profile)
        result_2d = model.calculate(50_000_000, advance_days=2)
        result_1d = model.calculate(50_000_000, advance_days=1)
        assert result_2d.fee_before_vat == pytest.approx(100_000, abs=1)
        assert result_1d.fee_before_vat == pytest.approx(100_000, abs=1)

    def test_flat_fee_rate_missing_raises(self):
        profile = CashAdvanceProfile(
            enabled=True,
            fee_model=FeeModel.FLAT_FEE,
            flat_fee_rate=None,
        )
        model = CashAdvanceModel(profile=profile)
        with pytest.raises(ValueError):
            model.calculate(50_000_000, advance_days=2)


class TestDoubleCountPrevention:
    def test_advance_uses_pending_not_settled(self):
        """
        After applying advance, the advanced amount comes from pending_cash,
        not from settled_cash. Verified via SettlementLedger integration.
        """
        from quant_vn.market.settlement import SettlementLedger
        import datetime

        ledger = SettlementLedger()
        trade_date = datetime.date(2026, 3, 2)
        settlement_date = datetime.date(2026, 3, 4)

        ledger.record_sell(
            trade_date=trade_date,
            symbol="FPT",
            quantity=1000,
            net_proceed=45_000_000,
            gross_sell_value=45_500_000,
            settlement_date=settlement_date,
        )

        # Before advance: settled = 0, pending = 45M
        assert ledger.available_cash_on(trade_date) == 0.0
        assert ledger.pending_cash_total() == pytest.approx(45_000_000, abs=1)

    def test_max_advance_amount(self):
        profile = CashAdvanceProfile(
            enabled=True,
            fee_model=FeeModel.DAILY_INTEREST,
            daily_rate=0.0003,
            max_advance_pct=0.9,
        )
        model = CashAdvanceModel(profile=profile)
        max_adv = model.max_advance_amount(50_000_000)
        assert max_adv == pytest.approx(45_000_000, abs=1)
