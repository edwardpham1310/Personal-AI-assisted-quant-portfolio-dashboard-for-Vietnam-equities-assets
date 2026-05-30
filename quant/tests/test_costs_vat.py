"""Tests for costs/vat.py — VAT on brokerage service fees."""

import pytest
from quant_vn.costs.vat import VATModel, VATResult, VAT_INCLUSIVE, VAT_EXCLUSIVE_10PCT, VAT_DISABLED


class TestVATModel:
    def test_vat_enabled_not_included(self):
        """Standard: VAT enabled, fee does NOT include VAT → vat = fee * rate."""
        model = VATModel(enabled=True, rate=0.10, fee_includes_vat=False)
        result = model.calculate(100_000)
        assert result.vat_amount == pytest.approx(10_000, abs=1)
        assert result.total_with_vat == pytest.approx(110_000, abs=1)

    def test_vat_enabled_already_included(self):
        """Fee already includes VAT → vat = 0 (no double-count)."""
        model = VATModel(enabled=True, rate=0.10, fee_includes_vat=True)
        result = model.calculate(110_000)
        assert result.vat_amount == 0.0
        assert result.total_with_vat == 110_000.0

    def test_vat_disabled(self):
        """VAT disabled → vat = 0 regardless of fee."""
        model = VATModel(enabled=False, rate=0.10, fee_includes_vat=False)
        result = model.calculate(100_000)
        assert result.vat_amount == 0.0
        assert result.total_with_vat == 100_000.0

    def test_vat_rate_zero(self):
        """Zero VAT rate → vat = 0."""
        model = VATModel(enabled=True, rate=0.0, fee_includes_vat=False)
        result = model.calculate(100_000)
        assert result.vat_amount == 0.0

    def test_vat_zero_brokerage_fee(self):
        """Zero fee → vat = 0."""
        model = VATModel(enabled=True, rate=0.10, fee_includes_vat=False)
        result = model.calculate(0.0)
        assert result.vat_amount == 0.0

    def test_vat_custom_rate(self):
        """Custom VAT rate is applied correctly."""
        model = VATModel(enabled=True, rate=0.08, fee_includes_vat=False)
        result = model.calculate(200_000)
        assert result.vat_amount == pytest.approx(16_000, abs=1)

    def test_total_fee_brokerage_plus_vat(self):
        """Total with VAT = brokerage + vat."""
        model = VATModel(enabled=True, rate=0.10, fee_includes_vat=False)
        result = model.calculate(100_000)
        assert result.total_with_vat == result.base_fee + result.vat_amount

    def test_no_double_count_regression(self):
        """Critical regression: fee_includes_vat=True must never add VAT again."""
        model = VATModel(enabled=True, rate=0.10, fee_includes_vat=True)
        fee_with_vat_baked_in = 110_000.0
        result = model.calculate(fee_with_vat_baked_in)
        total = fee_with_vat_baked_in + result.vat_amount
        # Must be 110_000, NOT 121_000
        assert total == pytest.approx(110_000, abs=1)

    def test_singleton_vat_inclusive(self):
        assert VAT_INCLUSIVE.fee_includes_vat is True
        assert VAT_INCLUSIVE.calculate(100_000).vat_amount == 0.0

    def test_singleton_vat_exclusive_10pct(self):
        assert not VAT_EXCLUSIVE_10PCT.fee_includes_vat
        assert VAT_EXCLUSIVE_10PCT.calculate(100_000).vat_amount == pytest.approx(10_000, abs=1)

    def test_singleton_vat_disabled(self):
        assert not VAT_DISABLED.enabled
        assert VAT_DISABLED.calculate(100_000).vat_amount == 0.0

    def test_round_trip_both_sides(self):
        """VAT computed independently on each side; total = buy_vat + sell_vat."""
        model = VAT_EXCLUSIVE_10PCT
        buy_vat = model.calculate(100_000).vat_amount    # 10_000
        sell_vat = model.calculate(90_000).vat_amount    # 9_000
        assert buy_vat + sell_vat == pytest.approx(19_000, abs=1)
