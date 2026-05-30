"""
Tests for recommendation/validator.py — BUY/SELL recommendation validation.

Tests 13-20 from specification:
    Test 13: Sell creates pending cash (covered in settlement tests)
    Test 14: Pending cash unavailable by default
    Test 15: Cash advance enabled (integration)
    Test 18: BUY with pending cash, advance disabled → reject
    Test 19: BUY with auto cash advance → output includes advance estimate
    Test 20: SELL recommendation output includes settlement date
"""

import datetime
import pytest
from quant_vn.recommendation.validator import (
    RecommendationValidator,
    RecommendationPayload,
    ValidationSeverity,
)
from quant_vn.costs.transaction import TransactionCostModel
from quant_vn.costs.brokerage import BrokerFeeProfile
from quant_vn.costs.vat import VAT_DISABLED
from quant_vn.costs.taxes import TaxProfile
from quant_vn.costs.slippage import FixedBpsSlippageModel
from quant_vn.costs.cash_advance import CashAdvanceProfile, CashAdvanceModel, FeeModel


def _clean_model():
    """Cost model with no VAT, no slippage for clean assertions."""
    return TransactionCostModel(
        broker_profile=BrokerFeeProfile.custom(rate=0.0015, fee_includes_vat=False),
        tax_profile=TaxProfile(),
        vat_model=VAT_DISABLED,
        slippage_model=FixedBpsSlippageModel(bps=0.0),
    )


def _advance_model():
    return CashAdvanceModel(
        profile=CashAdvanceProfile(
            enabled=True,
            fee_model=FeeModel.DAILY_INTEREST,
            daily_rate=0.0003,
            minimum_fee=0,
            vat_enabled=False,
        )
    )


class TestValidBuyRecommendation:
    def test_valid_buy_passes(self):
        validator = RecommendationValidator(cost_model=_clean_model())
        payload = RecommendationPayload(
            action="BUY",
            symbol="FPT",
            quantity=1000,
            price=86_000,
            trade_date=datetime.date(2026, 3, 2),
            settled_cash=100_000_000,
            reference_price=85_000,
            exchange="HOSE",
            avg_daily_value_20d=50_000_000_000,
        )
        result = validator.validate(payload)
        assert result.approved is True

    def test_buy_output_contains_total_cash_required(self):
        validator = RecommendationValidator(cost_model=_clean_model())
        payload = RecommendationPayload(
            action="BUY", symbol="FPT", quantity=1000, price=50_000,
            trade_date=datetime.date(2026, 3, 2),
            settled_cash=100_000_000,
            reference_price=50_000,
            exchange="HOSE",
            avg_daily_value_20d=50_000_000_000,
        )
        result = validator.validate(payload)
        # 50M + 75K brokerage = 50,075,000
        assert result.total_cash_required == pytest.approx(50_075_000, abs=100)
        assert result.brokerage_fee == pytest.approx(75_000, abs=100)
        assert result.settlement_date is not None


class TestBuyWithPendingCash:
    def test_buy_with_pending_cash_no_advance_warns(self):
        """Test 18: settled_cash insufficient, pending exists, advance disabled → reject."""
        validator = RecommendationValidator(cost_model=_clean_model())
        payload = RecommendationPayload(
            action="BUY", symbol="FPT", quantity=1000, price=50_000,
            trade_date=datetime.date(2026, 3, 2),
            settled_cash=10_000_000,    # insufficient
            pending_cash=50_000_000,    # but pending exists
            reference_price=50_000,
            exchange="HOSE",
            avg_daily_value_20d=50_000_000_000,
            allow_auto_advance_for_buying_power=False,
        )
        result = validator.validate(payload)
        assert result.approved is False
        warning_codes = [w.code for w in result.warnings]
        error_codes = [e.code for e in result.errors]
        assert "PENDING_CASH_EXISTS" in warning_codes
        assert "INSUFFICIENT_SETTLED_CASH" in error_codes

    def test_buy_with_auto_advance(self):
        """Test 19: auto-advance enabled → output includes advance estimate."""
        validator = RecommendationValidator(
            cost_model=_clean_model(),
            cash_advance_model=_advance_model(),
        )
        payload = RecommendationPayload(
            action="BUY", symbol="FPT", quantity=1000, price=50_000,
            trade_date=datetime.date(2026, 3, 2),
            settled_cash=10_000_000,
            pending_cash=50_000_000,
            reference_price=50_000,
            exchange="HOSE",
            avg_daily_value_20d=50_000_000_000,
            allow_auto_advance_for_buying_power=True,
        )
        result = validator.validate(payload)
        # Should include advance estimate
        assert result.estimated_advance_amount > 0
        assert result.estimated_advance_fee >= 0
        warning_codes = [w.code for w in result.warnings]
        assert "CASH_ADVANCE_REQUIRED" in warning_codes


class TestBuyWithInvalidLotSize:
    def test_buy_odd_lot_rejected(self):
        validator = RecommendationValidator(cost_model=_clean_model())
        payload = RecommendationPayload(
            action="BUY", symbol="FPT", quantity=155,
            price=50_000, trade_date=datetime.date(2026, 3, 2),
            settled_cash=100_000_000,
            reference_price=50_000, exchange="HOSE",
            avg_daily_value_20d=50_000_000_000,
        )
        result = validator.validate(payload)
        assert result.approved is False
        error_codes = [e.code for e in result.errors]
        assert "LOT_SIZE" in error_codes


class TestBuyAbovePriceCeiling:
    def test_buy_above_ceiling_rejected(self):
        """Test 11 integration: buy price above ceiling → reject."""
        validator = RecommendationValidator(cost_model=_clean_model())
        payload = RecommendationPayload(
            action="BUY", symbol="FPT", quantity=1000,
            price=108_000,    # ref 100K * 1.08 → above 7% ceiling
            trade_date=datetime.date(2026, 3, 2),
            settled_cash=200_000_000,
            reference_price=100_000,
            exchange="HOSE",
            avg_daily_value_20d=50_000_000_000,
        )
        result = validator.validate(payload)
        assert result.approved is False
        error_codes = [e.code for e in result.errors]
        assert "PRICE_LIMIT" in error_codes


class TestSellRecommendation:
    def test_sell_valid_with_settled_shares(self):
        validator = RecommendationValidator(cost_model=_clean_model())
        payload = RecommendationPayload(
            action="SELL", symbol="FPT", quantity=500,
            price=55_000, trade_date=datetime.date(2026, 3, 2),
            settled_shares={"FPT": 1000},
            reference_price=54_000, exchange="HOSE",
            avg_daily_value_20d=50_000_000_000,
        )
        result = validator.validate(payload)
        assert result.approved is True
        # Test 20: settlement date is present
        assert result.settlement_date is not None
        # Net proceeds calculated
        assert result.net_proceeds > 0

    def test_sell_pending_shares_rejected(self):
        """Cannot sell shares still pending settlement."""
        validator = RecommendationValidator(cost_model=_clean_model())
        payload = RecommendationPayload(
            action="SELL", symbol="FPT", quantity=500,
            price=55_000, trade_date=datetime.date(2026, 3, 2),
            settled_shares={"FPT": 0},
            pending_shares={"FPT": 1000},
            reference_price=54_000, exchange="HOSE",
        )
        result = validator.validate(payload)
        assert result.approved is False
        error_codes = [e.code for e in result.errors]
        assert "SHARES_PENDING_SETTLEMENT" in error_codes

    def test_sell_no_position_rejected(self):
        validator = RecommendationValidator(cost_model=_clean_model())
        payload = RecommendationPayload(
            action="SELL", symbol="FPT", quantity=500,
            price=55_000, trade_date=datetime.date(2026, 3, 2),
            settled_shares={},
            reference_price=54_000, exchange="HOSE",
        )
        result = validator.validate(payload)
        assert result.approved is False

    def test_sell_output_shows_pending_proceeds_warning(self):
        """Test 20: SELL must warn that proceeds are pending until settlement."""
        validator = RecommendationValidator(cost_model=_clean_model())
        payload = RecommendationPayload(
            action="SELL", symbol="FPT", quantity=500,
            price=55_000, trade_date=datetime.date(2026, 3, 2),
            settled_shares={"FPT": 1000},
            reference_price=54_000, exchange="HOSE",
        )
        result = validator.validate(payload)
        warning_codes = [w.code for w in result.warnings]
        assert "PROCEEDS_PENDING" in warning_codes

    def test_sell_with_advance_shows_option(self):
        """SELL with advance enabled shows cash advance option in output."""
        validator = RecommendationValidator(
            cost_model=_clean_model(),
            cash_advance_model=_advance_model(),
        )
        payload = RecommendationPayload(
            action="SELL", symbol="FPT", quantity=500,
            price=55_000, trade_date=datetime.date(2026, 3, 2),
            settled_shares={"FPT": 1000},
            reference_price=54_000, exchange="HOSE",
        )
        result = validator.validate(payload)
        warning_codes = [w.code for w in result.warnings]
        assert "CASH_ADVANCE_AVAILABLE" in warning_codes
        assert result.estimated_net_advance_cash > 0


class TestUnknownAction:
    def test_unknown_action_rejected(self):
        validator = RecommendationValidator(cost_model=_clean_model())
        payload = RecommendationPayload(
            action="HOLD", symbol="FPT", quantity=100, price=50_000,
            trade_date=datetime.date(2026, 3, 2),
        )
        result = validator.validate(payload)
        assert result.approved is False
        error_codes = [e.code for e in result.errors]
        assert "UNKNOWN_ACTION" in error_codes


class TestVATDoubleCountingRegression:
    """Test 12: VAT double counting prevention."""

    def test_vat_not_double_counted_when_included(self):
        """If broker fee includes VAT, validator must not add VAT again."""
        from quant_vn.costs.vat import VATModel
        model = TransactionCostModel(
            broker_profile=BrokerFeeProfile.custom(rate=0.0015, fee_includes_vat=True),
            tax_profile=TaxProfile(),
            vat_model=VATModel(enabled=True, rate=0.10, fee_includes_vat=True),
            slippage_model=FixedBpsSlippageModel(bps=0.0),
        )
        validator = RecommendationValidator(cost_model=model)
        payload = RecommendationPayload(
            action="BUY", symbol="FPT", quantity=1000, price=50_000,
            trade_date=datetime.date(2026, 3, 2),
            settled_cash=100_000_000,
            reference_price=50_000, exchange="HOSE",
            avg_daily_value_20d=50_000_000_000,
        )
        result = validator.validate(payload)
        assert result.vat_amount == 0.0
        # total_cash_required = 50M + 75K brokerage + 0 VAT = 50,075,000
        assert result.total_cash_required == pytest.approx(50_075_000, abs=100)
