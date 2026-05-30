"""
Tests for costs/transaction.py — TransactionCostModel facade.

Tests 1-3 from specification:
    Test 1: Buy cost calculation (1000 shares @ 50,000 VND, 0.15% brokerage)
    Test 2: Sell tax calculation (1000 shares @ 55,000 VND)
    Test 3: Full round-trip PnL
"""

import pytest
from quant_vn.costs.transaction import TransactionCostModel, TransactionCostBreakdown
from quant_vn.costs.brokerage import BrokerFeeProfile
from quant_vn.costs.vat import VATModel, VAT_DISABLED, VAT_EXCLUSIVE_10PCT
from quant_vn.costs.taxes import SellTaxModel, TaxProfile
from quant_vn.costs.slippage import FixedBpsSlippageModel


def _model_no_vat_no_slippage(commission_rate=0.0015, sell_tax_rate=0.001):
    """Test model with no VAT, no slippage — for clean formula verification."""
    return TransactionCostModel(
        broker_profile=BrokerFeeProfile.custom(rate=commission_rate, min_fee_vnd=0, fee_includes_vat=False),
        tax_profile=TaxProfile(sell_tax=SellTaxModel(rate=sell_tax_rate)),
        vat_model=VAT_DISABLED,
        slippage_model=FixedBpsSlippageModel(bps=0.0),
    )


class TestTest1_BuyCostCalculation:
    """Test 1: Buy 1000 shares @ 50,000 VND, brokerage 0.15%, VAT disabled, slippage 0."""

    def test_transaction_value(self):
        model = _model_no_vat_no_slippage(commission_rate=0.0015)
        bd = model.buy_cost(50_000_000, quantity=1000, price=50_000)
        assert bd.notional == pytest.approx(50_000_000, abs=1)

    def test_brokerage_fee(self):
        model = _model_no_vat_no_slippage(commission_rate=0.0015)
        bd = model.buy_cost(50_000_000, quantity=1000, price=50_000)
        # 50M * 0.15% = 75,000 VND
        assert bd.brokerage_fee == pytest.approx(75_000, abs=1)

    def test_total_cash_required_no_vat(self):
        model = _model_no_vat_no_slippage(commission_rate=0.0015)
        bd = model.buy_cost(50_000_000, quantity=1000, price=50_000)
        # 50M + 75K = 50,075,000 VND
        assert bd.total_cash_required == pytest.approx(50_075_000, abs=1)

    def test_vat_zero_when_disabled(self):
        model = _model_no_vat_no_slippage(commission_rate=0.0015)
        bd = model.buy_cost(50_000_000, quantity=1000, price=50_000)
        assert bd.vat_amount == 0.0

    def test_sell_tax_zero_on_buy(self):
        model = _model_no_vat_no_slippage()
        bd = model.buy_cost(50_000_000, quantity=1000, price=50_000)
        assert bd.sell_tax == 0.0

    def test_total_cash_required_with_vat(self):
        """With VAT enabled (not included), total should include VAT on brokerage."""
        model = TransactionCostModel(
            broker_profile=BrokerFeeProfile.custom(rate=0.0015, fee_includes_vat=False),
            tax_profile=TaxProfile(),
            vat_model=VAT_EXCLUSIVE_10PCT,
            slippage_model=FixedBpsSlippageModel(bps=0.0),
        )
        bd = model.buy_cost(50_000_000, quantity=1000, price=50_000)
        # brokerage = 75,000; VAT = 7,500; total = 50M + 82,500 = 50,082,500
        assert bd.brokerage_fee == pytest.approx(75_000, abs=1)
        assert bd.vat_amount == pytest.approx(7_500, abs=1)
        assert bd.total_cash_required == pytest.approx(50_082_500, abs=100)


class TestTest2_SellTaxCalculation:
    """Test 2: Sell 1000 shares @ 55,000 VND, brokerage 0.15%, sell tax 0.1%."""

    def test_gross_sell_value(self):
        model = _model_no_vat_no_slippage(commission_rate=0.0015, sell_tax_rate=0.001)
        bd = model.sell_cost(55_000_000, quantity=1000, price=55_000)
        assert bd.notional == pytest.approx(55_000_000, abs=1)

    def test_sell_brokerage_fee(self):
        model = _model_no_vat_no_slippage(commission_rate=0.0015, sell_tax_rate=0.001)
        bd = model.sell_cost(55_000_000, quantity=1000, price=55_000)
        # 55M * 0.15% = 82,500 VND
        assert bd.brokerage_fee == pytest.approx(82_500, abs=1)

    def test_sell_tax_on_gross(self):
        model = _model_no_vat_no_slippage(commission_rate=0.0015, sell_tax_rate=0.001)
        bd = model.sell_cost(55_000_000, quantity=1000, price=55_000)
        # 55M * 0.1% = 55,000 VND
        assert bd.sell_tax == pytest.approx(55_000, abs=1)

    def test_net_proceeds(self):
        model = _model_no_vat_no_slippage(commission_rate=0.0015, sell_tax_rate=0.001)
        bd = model.sell_cost(55_000_000, quantity=1000, price=55_000)
        # 55M - 82,500 - 55,000 = 54,862,500
        assert bd.net_proceeds == pytest.approx(54_862_500, abs=100)


class TestTest3_FullRoundTripPnL:
    """Test 3: Buy 1000 @ 50K, Sell 1000 @ 55K. Verify realized PnL."""

    def test_realized_pnl(self):
        model = _model_no_vat_no_slippage(commission_rate=0.0015, sell_tax_rate=0.001)

        buy_bd = model.buy_cost(50_000_000, quantity=1000, price=50_000)
        sell_bd = model.sell_cost(55_000_000, quantity=1000, price=55_000)

        # cost_basis = notional + buy_fee = 50M + 75K = 50,075,000
        cost_basis = buy_bd.notional + buy_bd.brokerage_fee
        net_proceeds = sell_bd.net_proceeds

        realized_pnl = net_proceeds - cost_basis
        # net_proceeds ≈ 54,862,500; cost_basis = 50,075,000; PnL ≈ 4,787,500
        assert realized_pnl == pytest.approx(4_787_500, abs=500)

    def test_net_return_lower_than_gross(self):
        """Net return must be lower than gross return (costs reduce return)."""
        model = _model_no_vat_no_slippage(commission_rate=0.0015, sell_tax_rate=0.001)

        buy_bd = model.buy_cost(50_000_000, quantity=1000, price=50_000)
        sell_bd = model.sell_cost(55_000_000, quantity=1000, price=55_000)

        gross_pnl = 55_000_000 - 50_000_000  # 5,000,000
        cost_basis = buy_bd.notional + buy_bd.brokerage_fee
        realized_pnl = sell_bd.net_proceeds - cost_basis

        gross_return = gross_pnl / 50_000_000
        net_return = realized_pnl / cost_basis

        assert net_return < gross_return

    def test_from_legacy_matches_old_arithmetic(self):
        """from_legacy() must produce EXACTLY the same result as old TransactionCosts."""
        from quant_vn.market.costs import TransactionCosts

        legacy = TransactionCosts(commission_rate=0.001, sell_tax_rate=0.001, slippage_bps=10)
        new_model = TransactionCostModel.from_legacy(
            commission_rate=0.001, sell_tax_rate=0.001, slippage_bps=10
        )

        notional = 100_000_000.0
        qty = 1000.0
        price = 100_000.0

        old_buy = legacy.buy_cost(notional)
        new_buy = new_model.buy_cost(notional, quantity=qty, price=price).total_cost
        assert new_buy == pytest.approx(old_buy, rel=1e-6)

        old_sell = legacy.sell_cost(notional)
        new_sell = new_model.sell_cost(notional, quantity=qty, price=price).total_cost
        assert new_sell == pytest.approx(old_sell, rel=1e-6)

    def test_side_field_correct(self):
        model = _model_no_vat_no_slippage()
        assert model.buy_cost(10_000_000).side == "buy"
        assert model.sell_cost(10_000_000).side == "sell"

    def test_total_cost_equals_sum_of_components(self):
        model = TransactionCostModel(
            broker_profile=BrokerFeeProfile.custom(rate=0.0015, fee_includes_vat=False),
            tax_profile=TaxProfile(),
            vat_model=VAT_EXCLUSIVE_10PCT,
            slippage_model=FixedBpsSlippageModel(bps=10.0),
        )
        bd = model.sell_cost(100_000_000, quantity=1000, price=100_000)
        expected = bd.brokerage_fee + bd.vat_amount + bd.sell_tax + bd.slippage_cost
        assert bd.total_cost == pytest.approx(expected, abs=1)
