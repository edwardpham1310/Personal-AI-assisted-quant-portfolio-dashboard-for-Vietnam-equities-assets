"""Tests for costs/taxes.py — Sell tax and dividend tax models."""

import pytest
from quant_vn.costs.taxes import (
    SellTaxModel, DividendTaxModel, StockDividendTaxModel, TaxProfile,
    VIETNAM_DEFAULT_TAXES,
)


class TestSellTaxModel:
    def test_sell_tax_100m(self):
        """Standard 0.1% sell tax on 100M VND gross sell value."""
        model = SellTaxModel(rate=0.001)
        result = model.calculate(100_000_000)
        assert result.tax_amount == pytest.approx(100_000, abs=1)

    def test_sell_tax_applied_to_gross_not_net(self):
        """Sell tax is on GROSS sell value, not net-of-brokerage.

        This test verifies the difference is meaningful — the caller must
        pass gross_sell_value, not (sell_value - brokerage_fee).
        """
        gross = 100_000_000.0
        brokerage = 150_000.0
        net = gross - brokerage

        tax_on_gross = SellTaxModel(0.001).calculate(gross).tax_amount
        tax_on_net = SellTaxModel(0.001).calculate(net).tax_amount

        assert tax_on_gross == pytest.approx(100_000, abs=1)
        assert tax_on_net == pytest.approx(99_850, abs=1)
        # The difference matters
        assert tax_on_gross != tax_on_net

    def test_sell_tax_zero_value(self):
        assert SellTaxModel(0.001).calculate(0.0).tax_amount == 0.0

    def test_sell_tax_custom_rate(self):
        result = SellTaxModel(rate=0.002).calculate(100_000_000)
        assert result.tax_amount == pytest.approx(200_000, abs=1)

    def test_sell_tax_not_on_buy_side(self):
        """SellTaxModel must never be called on the buy side.
        This test documents the contract: sell_tax should be 0 for buys.
        """
        from quant_vn.costs.transaction import TransactionCostModel
        model = TransactionCostModel.from_legacy(commission_rate=0.001, sell_tax_rate=0.001)
        buy_bd = model.buy_cost(100_000_000, quantity=1000, price=100_000)
        assert buy_bd.sell_tax == 0.0

    def test_sell_tax_negative_raises(self):
        with pytest.raises(ValueError):
            SellTaxModel(0.001).calculate(-1_000_000)

    def test_sell_tax_type_field(self):
        result = SellTaxModel(0.001).calculate(50_000_000)
        assert result.tax_type == "sell_tax"


class TestDividendTaxModel:
    def test_dividend_tax_standard(self):
        """5% tax on 20M VND cash dividend."""
        result = DividendTaxModel(rate=0.05).calculate(20_000_000)
        assert result.tax_amount == pytest.approx(1_000_000, abs=1)

    def test_dividend_tax_zero(self):
        result = DividendTaxModel(0.05).calculate(0.0)
        assert result.tax_amount == 0.0

    def test_dividend_tax_custom_rate(self):
        result = DividendTaxModel(rate=0.10).calculate(10_000_000)
        assert result.tax_amount == pytest.approx(1_000_000, abs=1)

    def test_dividend_tax_type_field(self):
        result = DividendTaxModel(0.05).calculate(1_000_000)
        assert result.tax_type == "dividend_tax"

    def test_dividend_tax_negative_raises(self):
        with pytest.raises(ValueError):
            DividendTaxModel(0.05).calculate(-1_000)


class TestStockDividendTaxModel:
    def test_stock_dividend_raises_not_implemented(self):
        """StockDividendTaxModel must raise NotImplementedError until rules are confirmed."""
        model = StockDividendTaxModel()
        with pytest.raises(NotImplementedError):
            model.calculate(10_000_000)


class TestTaxProfile:
    def test_default_profile_uses_vietnam_rates(self):
        profile = TaxProfile()
        assert profile.sell_tax.rate == pytest.approx(0.001)
        assert profile.dividend_cash_tax.rate == pytest.approx(0.05)

    def test_vietnam_default_taxes_singleton(self):
        result = VIETNAM_DEFAULT_TAXES.sell_tax.calculate(100_000_000)
        assert result.tax_amount == pytest.approx(100_000, abs=1)
