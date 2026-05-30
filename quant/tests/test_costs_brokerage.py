"""Tests for costs/brokerage.py — Broker fee models."""

import pytest
from quant_vn.costs.brokerage import (
    FlatFeeModel, TieredFeeModel, FeeTier, BrokerFeeProfile,
)


class TestFlatFeeModel:
    def test_above_minimum(self):
        model = FlatFeeModel(rate=0.0015, min_fee_vnd=10_000)
        result = model.calculate(10_000_000)
        assert result.base_fee == pytest.approx(15_000, abs=1)
        assert not result.min_fee_applied

    def test_below_minimum(self):
        """Fee below minimum → minimum is applied."""
        model = FlatFeeModel(rate=0.0015, min_fee_vnd=10_000)
        result = model.calculate(1_000_000)   # 1M * 0.15% = 1500 < 10000
        assert result.base_fee == pytest.approx(10_000, abs=1)
        assert result.min_fee_applied

    def test_zero_minimum(self):
        model = FlatFeeModel(rate=0.0015, min_fee_vnd=0.0)
        result = model.calculate(1_000_000)
        assert result.base_fee == pytest.approx(1_500, abs=1)
        assert not result.min_fee_applied

    def test_large_notional(self):
        model = FlatFeeModel(rate=0.001, min_fee_vnd=10_000)
        result = model.calculate(10_000_000_000)
        assert result.base_fee == pytest.approx(10_000_000, abs=1)

    def test_zero_notional_returns_minimum(self):
        model = FlatFeeModel(rate=0.0015, min_fee_vnd=10_000)
        result = model.calculate(0.0)
        # 0 * rate = 0 < min_fee → min_fee applied
        assert result.base_fee == pytest.approx(10_000, abs=1)

    def test_negative_notional_raises(self):
        model = FlatFeeModel(rate=0.0015, min_fee_vnd=10_000)
        with pytest.raises(ValueError):
            model.calculate(-1_000_000)

    def test_rate_used_field(self):
        model = FlatFeeModel(rate=0.0015, min_fee_vnd=0)
        result = model.calculate(10_000_000)
        assert result.rate_used == pytest.approx(0.0015)

    def test_notional_in_result(self):
        model = FlatFeeModel(rate=0.0015, min_fee_vnd=0)
        result = model.calculate(50_000_000)
        assert result.notional == pytest.approx(50_000_000)


class TestTieredFeeModel:
    """
    VNDIRECT DBA example tiers (sorted descending by threshold):
        >= 800M VND/day → 0.15%
        >= 400M VND/day → 0.20%
        >= 250M VND/day → 0.25%
        >= 80M VND/day  → 0.30%
        >=  0M VND/day  → 0.35%
    """

    @pytest.fixture
    def vndirect_dba_model(self):
        tiers = [
            FeeTier(min_daily_value=800_000_000, fee_rate=0.0015),
            FeeTier(min_daily_value=400_000_000, fee_rate=0.0020),
            FeeTier(min_daily_value=250_000_000, fee_rate=0.0025),
            FeeTier(min_daily_value= 80_000_000, fee_rate=0.0030),
            FeeTier(min_daily_value=          0, fee_rate=0.0035),
        ]
        return TieredFeeModel(tiers=tiers, min_fee_vnd=0.0)

    def test_first_tier(self, vndirect_dba_model):
        """cumulative >= 800M → 0.15% applied to full notional."""
        result = vndirect_dba_model.calculate(100_000_000, cumulative_daily_notional=900_000_000)
        assert result.rate_used == pytest.approx(0.0015)
        assert result.base_fee == pytest.approx(150_000, abs=1)

    def test_last_tier_no_cumulative(self, vndirect_dba_model):
        """cumulative = 0 → lowest rate 0.35%."""
        result = vndirect_dba_model.calculate(100_000_000, cumulative_daily_notional=0)
        assert result.rate_used == pytest.approx(0.0035)
        assert result.base_fee == pytest.approx(350_000, abs=1)

    def test_middle_tier(self, vndirect_dba_model):
        """cumulative in 400M-800M range → 0.20%."""
        result = vndirect_dba_model.calculate(50_000_000, cumulative_daily_notional=500_000_000)
        assert result.rate_used == pytest.approx(0.0020)
        assert result.base_fee == pytest.approx(100_000, abs=1)

    def test_tier_applies_to_full_notional(self, vndirect_dba_model):
        """Rate applies to full order notional (not marginal above threshold)."""
        # If cumulative = 850M and order = 200M, rate = 0.0015 on full 200M
        result = vndirect_dba_model.calculate(200_000_000, cumulative_daily_notional=850_000_000)
        assert result.base_fee == pytest.approx(300_000, abs=1)   # 200M * 0.15%

    def test_tiers_sorted_on_init(self):
        """Model must sort tiers correctly even if provided out of order."""
        tiers_unordered = [
            FeeTier(min_daily_value=0, fee_rate=0.003),
            FeeTier(min_daily_value=500_000_000, fee_rate=0.002),
            FeeTier(min_daily_value=1_000_000_000, fee_rate=0.001),
        ]
        model = TieredFeeModel(tiers=tiers_unordered)
        # cumulative 600M → should use 0.002 tier
        result = model.calculate(100_000_000, cumulative_daily_notional=600_000_000)
        assert result.rate_used == pytest.approx(0.002)

    def test_empty_tiers_raises(self):
        model = TieredFeeModel(tiers=[])
        with pytest.raises(ValueError):
            model.calculate(100_000_000)

    def test_negative_notional_raises(self, vndirect_dba_model):
        with pytest.raises(ValueError):
            vndirect_dba_model.calculate(-100_000)


class TestBrokerFeeProfile:
    def test_ssi_active_online_factory(self):
        profile = BrokerFeeProfile.ssi_active_online()
        assert profile.broker_name == "SSI"
        result = profile.calculate_fee(100_000_000)
        assert result.base_fee == pytest.approx(150_000, abs=1)

    def test_vndirect_dta_online_factory(self):
        profile = BrokerFeeProfile.vndirect_dta_online()
        assert profile.broker_name == "VNDIRECT"
        result = profile.calculate_fee(100_000_000)
        assert result.base_fee == pytest.approx(100_000, abs=1)

    def test_custom_factory(self):
        profile = BrokerFeeProfile.custom(rate=0.002, min_fee_vnd=15_000, fee_includes_vat=True)
        assert profile.fee_includes_vat is True
        result = profile.calculate_fee(10_000_000)
        assert result.base_fee == pytest.approx(20_000, abs=1)

    def test_flat_default_matches_legacy(self):
        """flat_default() must match the old TransactionCosts commission_rate=0.001."""
        profile = BrokerFeeProfile.flat_default()
        result = profile.calculate_fee(100_000_000)
        assert result.base_fee == pytest.approx(100_000, abs=1)
