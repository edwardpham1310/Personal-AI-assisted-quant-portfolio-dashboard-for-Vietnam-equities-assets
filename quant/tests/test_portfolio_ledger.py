"""Tests for portfolio/ledger.py — PortfolioLedger with T+2 awareness."""

import datetime
import pytest
from quant_vn.portfolio.ledger import PortfolioLedger
from quant_vn.costs.transaction import TransactionCostModel
from quant_vn.costs.brokerage import BrokerFeeProfile
from quant_vn.costs.vat import VAT_DISABLED
from quant_vn.costs.taxes import TaxProfile
from quant_vn.costs.slippage import FixedBpsSlippageModel
from quant_vn.costs.cash_advance import (
    CashAdvanceModel, CashAdvanceProfile, FeeModel,
)
from quant_vn.market.settlement import AssetType
from quant_vn.market.calendar import t2_settlement_date


def _clean_cost_model():
    return TransactionCostModel(
        broker_profile=BrokerFeeProfile.custom(rate=0.0015, fee_includes_vat=False),
        tax_profile=TaxProfile(),
        vat_model=VAT_DISABLED,
        slippage_model=FixedBpsSlippageModel(bps=0.0),
    )


def _advance_model():
    return CashAdvanceModel(profile=CashAdvanceProfile(
        enabled=True, fee_model=FeeModel.DAILY_INTEREST,
        daily_rate=0.0003, minimum_fee=0, vat_enabled=False,
    ))


class TestPortfolioLedgerBuy:
    def test_buy_deducts_settled_cash(self):
        ledger = PortfolioLedger(initial_capital=100_000_000, cost_model=_clean_cost_model())
        trade_date = datetime.date(2026, 3, 2)
        ledger.process_buy(trade_date, "FPT", quantity=1000, price=50_000)
        # 100M - 50M - 75K brokerage = 49,925,000
        snap = ledger.snapshot(trade_date, market_prices={"FPT": 50_000})
        assert snap.settled_cash == pytest.approx(49_925_000, abs=100)

    def test_buy_shares_not_immediately_sellable(self):
        ledger = PortfolioLedger(initial_capital=100_000_000, cost_model=_clean_cost_model())
        trade_date = datetime.date(2026, 3, 2)
        ledger.process_buy(trade_date, "FPT", quantity=1000, price=50_000)
        # On trade date: shares are pending, not sellable
        assert ledger.available_shares("FPT", trade_date) == 0
        assert ledger.can_sell("FPT", 1000, trade_date) is False


class TestPortfolioLedgerSell:
    def test_sell_creates_pending_cash(self):
        """Test 13: Sell proceeds go to pending_cash, not settled_cash."""
        ledger = PortfolioLedger(
            initial_capital=100_000_000, cost_model=_clean_cost_model()
        )
        # Pre-seed settled shares
        ledger._ledger.add_settled_shares("FPT", 1000)
        trade_date = datetime.date(2026, 3, 2)
        ledger.process_sell(trade_date, "FPT", quantity=500, price=55_000)
        snap = ledger.snapshot(trade_date)
        # settled_cash should still be 100M (sell proceeds are pending)
        assert snap.settled_cash == pytest.approx(100_000_000, abs=1)
        assert snap.pending_cash > 0


class TestPortfolioLedgerSettlement:
    def test_advance_date_settles_buys(self):
        ledger = PortfolioLedger(initial_capital=100_000_000, cost_model=_clean_cost_model())
        trade_date = datetime.date(2026, 3, 2)  # Monday
        ledger.process_buy(trade_date, "FPT", quantity=1000, price=50_000)
        settlement = t2_settlement_date(trade_date)
        ledger.advance_date(settlement)
        assert ledger.available_shares("FPT", settlement) == 1000

    def test_advance_date_settles_sells(self):
        ledger = PortfolioLedger(initial_capital=100_000_000, cost_model=_clean_cost_model())
        ledger._ledger.add_settled_shares("FPT", 1000)
        trade_date = datetime.date(2026, 3, 2)
        result = ledger.process_sell(trade_date, "FPT", quantity=500, price=55_000)
        settlement = t2_settlement_date(trade_date)
        snap_before = ledger.snapshot(trade_date)
        ledger.advance_date(settlement)
        snap_after = ledger.snapshot(settlement)
        # Settled cash increases by net_proceeds
        assert snap_after.settled_cash > snap_before.settled_cash
        # pending_cash drops
        assert snap_after.pending_cash < snap_before.pending_cash


class TestPortfolioLedgerAdvance:
    def test_advance_increases_available_cash(self):
        """Test 15: Cash advance increases available cash by net advance."""
        ledger = PortfolioLedger(
            initial_capital=100_000_000,
            cost_model=_clean_cost_model(),
            cash_advance_model=_advance_model(),
        )
        ledger._ledger.add_settled_shares("FPT", 1000)
        trade_date = datetime.date(2026, 3, 2)
        sell_result = ledger.process_sell(trade_date, "FPT", quantity=1000, price=50_000)
        entry_id = sell_result["pending_entry_id"]

        cash_before = ledger.snapshot(trade_date).settled_cash
        adv_result = ledger.apply_advance(
            entry_id=entry_id,
            advanced_amount=49_000_000,
            advance_days=2,
            advance_date=trade_date,
            settlement_date=t2_settlement_date(trade_date),
        )
        cash_after = ledger.snapshot(trade_date).settled_cash
        # Cash should increase by net_advanced_cash
        assert cash_after > cash_before
        assert adv_result["net_advanced_cash"] < 49_000_000  # less than advance due to fee

    def test_advance_no_double_count_at_settlement(self):
        """Test 16: After advance + settlement, no duplicate cash."""
        ledger = PortfolioLedger(
            initial_capital=100_000_000,
            cost_model=_clean_cost_model(),
            cash_advance_model=_advance_model(),
        )
        ledger._ledger.add_settled_shares("FPT", 1000)
        trade_date = datetime.date(2026, 3, 2)
        sell_result = ledger.process_sell(trade_date, "FPT", quantity=1000, price=50_000)
        entry_id = sell_result["pending_entry_id"]
        ledger.apply_advance(
            entry_id=entry_id,
            advanced_amount=sell_result["net_proceeds"],
            advance_days=2,
            advance_date=trade_date,
            settlement_date=t2_settlement_date(trade_date),
        )
        cash_after_advance = ledger.snapshot(trade_date).settled_cash
        # Advance date through settlement
        ledger.advance_date(t2_settlement_date(trade_date))
        cash_after_settlement = ledger.snapshot(t2_settlement_date(trade_date)).settled_cash
        # No additional cash should be added at settlement (ADVANCED → SETTLED but cash unchanged)
        assert cash_after_settlement == pytest.approx(cash_after_advance, abs=1)


class TestAllowUseUnsettledCash:
    def test_disabled_default(self):
        ledger = PortfolioLedger(initial_capital=100_000_000, cost_model=_clean_cost_model())
        ledger._ledger.add_settled_shares("FPT", 1000)
        trade_date = datetime.date(2026, 3, 2)
        ledger.process_sell(trade_date, "FPT", quantity=1000, price=50_000)
        # Default: available_cash = settled only
        avail = ledger.available_cash(trade_date)
        assert avail == pytest.approx(100_000_000, abs=1)

    def test_enabled_includes_pending(self):
        ledger = PortfolioLedger(
            initial_capital=100_000_000,
            cost_model=_clean_cost_model(),
            allow_use_unsettled_cash=True,
        )
        ledger._ledger.add_settled_shares("FPT", 1000)
        trade_date = datetime.date(2026, 3, 2)
        ledger.process_sell(trade_date, "FPT", quantity=1000, price=50_000)
        avail = ledger.available_cash(trade_date)
        # Should include pending
        assert avail > 100_000_000
