"""
Regression tests for Phase 2 post-review fixes.

These tests cover bugs found by the Reality Checker review and verify they
do not return.

Bugs fixed:
    C1 — process_buy cost basis included slippage (overstated cost basis,
         understated realized PnL).
    C2 — available_cash_on / available_shares_on ignored as_of_date and did
         not auto-advance settlement.
    C3 — PendingSharesEntry used monkeypatch attribute for settled flag,
         not a proper dataclass field (serialization risk).
    H1 — Sell-side validator did not run liquidity check.
    H3 — record_buy / record_sell did not validate settlement_date >= trade_date.
    H4 — fee_includes_vat=None silently treated as False (no warning).
    H5 — Validator hardcoded advance_days=2 instead of computing actual
         (Friday→Tuesday = 4 calendar days).
    H7 — check_lot_size truncated floats — 100.5 silently became 100 (passed).
"""

import datetime
import warnings
import pytest

from quant_vn.market.settlement import SettlementLedger, PendingSharesEntry
from quant_vn.market.calendar import t2_settlement_date
from quant_vn.execution.rules import check_lot_size, RuleViolation
from quant_vn.portfolio.ledger import PortfolioLedger
from quant_vn.costs.transaction import TransactionCostModel
from quant_vn.costs.brokerage import BrokerFeeProfile, FlatFeeModel
from quant_vn.costs.vat import VAT_DISABLED, VATModel
from quant_vn.costs.taxes import TaxProfile, SellTaxModel
from quant_vn.costs.slippage import FixedBpsSlippageModel
from quant_vn.costs.cash_advance import (
    CashAdvanceModel, CashAdvanceProfile, FeeModel,
)
from quant_vn.recommendation.validator import (
    RecommendationValidator,
    RecommendationPayload,
)


class TestC1_CostBasisExcludesSlippage:
    """C1: cost basis must include only brokerage + VAT, NOT slippage.

    The buy slippage is already embedded in the execution price the trader paid;
    including it in cost basis again double-counts and understates realized PnL.
    """

    def test_realized_pnl_excludes_buy_slippage_from_cost_basis(self):
        # Cost model: brokerage 0.15%, no VAT, slippage 10 bps
        model = TransactionCostModel(
            broker_profile=BrokerFeeProfile.custom(rate=0.0015, fee_includes_vat=False),
            tax_profile=TaxProfile(sell_tax=SellTaxModel(rate=0.001)),
            vat_model=VAT_DISABLED,
            slippage_model=FixedBpsSlippageModel(bps=10.0),
        )
        ledger = PortfolioLedger(initial_capital=200_000_000, cost_model=model)

        trade_date = datetime.date(2026, 3, 2)
        # Buy 1000 @ 50K
        buy = ledger.process_buy(trade_date, "FPT", quantity=1000, price=50_000)
        # cost_basis per share should be: 50_000 + brokerage_fee/qty (NO slippage)
        # brokerage_fee = 50M * 0.0015 = 75_000; per share = 75
        # cost_basis per share = 50_075 VND (NOT 50_125 with 50 bps slippage)
        expected_cost_basis_per_share = 50_000 + 75_000 / 1000
        assert ledger._cost_basis["FPT"] == pytest.approx(expected_cost_basis_per_share, abs=1)

        # Verify by selling at break-even and checking realized PnL accounts only
        # for slippage-as-execution-difference, not slippage-in-cost-basis.
        # Settle shares
        ledger.advance_date(t2_settlement_date(trade_date))
        # Pre-seed actual settled shares for sell
        sell_date = datetime.date(2026, 3, 9)
        sell = ledger.process_sell(sell_date, "FPT", quantity=1000, price=50_075)
        # allocated cost basis = 50_075 * 1000 = 50_075_000 (matches buy cost basis)
        assert sell["allocated_cost_basis"] == pytest.approx(50_075_000, abs=1000)


class TestC2_AutoAdvanceSettlement:
    """C2: available_cash_on / available_shares_on must auto-advance settlement."""

    def test_available_cash_on_auto_settles_pending(self):
        ledger = SettlementLedger()
        ledger.set_initial_cash(100_000_000)
        trade_date = datetime.date(2024, 1, 8)   # Monday
        settlement = t2_settlement_date(trade_date)  # Wed Jan 10
        ledger.record_sell(
            trade_date=trade_date, symbol="FPT", quantity=1000,
            net_proceed=45_000_000, gross_sell_value=45_500_000,
            settlement_date=settlement,
        )
        # Query at settlement date directly — should auto-advance
        cash = ledger.available_cash_on(settlement)
        assert cash == pytest.approx(145_000_000, abs=1)

    def test_available_shares_on_auto_settles_pending(self):
        ledger = SettlementLedger()
        trade_date = datetime.date(2024, 1, 8)
        settlement = t2_settlement_date(trade_date)
        ledger.record_buy(trade_date, "FPT", 500, settlement)
        # Query at settlement directly
        qty = ledger.available_shares_on("FPT", settlement)
        assert qty == 500


class TestC3_PendingSharesSettledField:
    """C3: PendingSharesEntry must have a settled dataclass field, not monkeypatch."""

    def test_pending_shares_entry_has_settled_field(self):
        entry = PendingSharesEntry(
            entry_id="X1",
            symbol="FPT",
            buy_date=datetime.date(2024, 1, 8),
            settlement_date=datetime.date(2024, 1, 10),
            quantity=100,
            buy_price=50_000,
        )
        # Field exists and defaults to False
        assert hasattr(entry, "settled")
        assert entry.settled is False

    def test_pending_shares_settlement_idempotent(self):
        """Calling advance_date twice with same date must NOT double-credit."""
        ledger = SettlementLedger()
        trade_date = datetime.date(2024, 1, 8)
        settlement = t2_settlement_date(trade_date)
        ledger.record_buy(trade_date, "FPT", 500, settlement)
        ledger.advance_date(settlement)
        first = ledger.available_shares_on("FPT", settlement)
        ledger.advance_date(settlement)
        second = ledger.available_shares_on("FPT", settlement)
        assert first == second == 500


class TestH1_SellSideLiquidityCheck:
    """H1: Sell-side validator must run liquidity check."""

    def test_sell_above_5pct_adv_warns(self):
        model = TransactionCostModel(
            broker_profile=BrokerFeeProfile.custom(rate=0.0015, fee_includes_vat=False),
            tax_profile=TaxProfile(),
            vat_model=VAT_DISABLED,
            slippage_model=FixedBpsSlippageModel(bps=0.0),
        )
        validator = RecommendationValidator(cost_model=model)
        payload = RecommendationPayload(
            action="SELL", symbol="FPT", quantity=1000,
            price=100_000,  # order value = 100M
            trade_date=datetime.date(2026, 3, 2),
            settled_shares={"FPT": 5000},
            reference_price=100_000,
            exchange="HOSE",
            avg_daily_value_20d=1_000_000_000,  # 1B → order is 10% of ADV
        )
        result = validator.validate(payload)
        # Should produce a LIQUIDITY warning
        codes = [w.code for w in result.warnings]
        assert "LIQUIDITY" in codes


class TestH3_SettlementDateValidation:
    """H3: record_buy / record_sell must reject settlement_date < trade_date."""

    def test_record_buy_rejects_past_settlement(self):
        ledger = SettlementLedger()
        trade_date = datetime.date(2024, 1, 8)
        bad_settlement = datetime.date(2024, 1, 5)
        with pytest.raises(ValueError, match="cannot be before"):
            ledger.record_buy(trade_date, "FPT", 100, bad_settlement)

    def test_record_sell_rejects_past_settlement(self):
        ledger = SettlementLedger()
        trade_date = datetime.date(2024, 1, 8)
        bad_settlement = datetime.date(2024, 1, 5)
        with pytest.raises(ValueError):
            ledger.record_sell(
                trade_date=trade_date, symbol="FPT", quantity=100,
                net_proceed=1_000_000, gross_sell_value=1_010_000,
                settlement_date=bad_settlement,
            )

    def test_record_buy_rejects_zero_quantity(self):
        ledger = SettlementLedger()
        trade_date = datetime.date(2024, 1, 8)
        settlement = t2_settlement_date(trade_date)
        with pytest.raises(ValueError):
            ledger.record_buy(trade_date, "FPT", 0, settlement)


class TestH4_VATNoneWarns:
    """H4: fee_includes_vat=None must emit a warning when used."""

    def test_constructing_with_none_vat_status_warns(self):
        profile_none = BrokerFeeProfile(
            broker_name="TEST",
            account_type="DEFAULT",
            channel="online",
            fee_model=FlatFeeModel(rate=0.0015),
            fee_includes_vat=None,   # unverified
        )
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            TransactionCostModel(broker_profile=profile_none)
            assert len(caught) >= 1
            assert any("fee_includes_vat" in str(w.message) for w in caught)

    def test_constructing_with_explicit_false_no_warning(self):
        profile_explicit = BrokerFeeProfile.custom(rate=0.0015, fee_includes_vat=False)
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            TransactionCostModel(broker_profile=profile_explicit)
            # No fee_includes_vat warning when explicit
            relevant = [w for w in caught if "fee_includes_vat" in str(w.message)]
            assert relevant == []


class TestH5_ValidatorComputesActualAdvanceDays:
    """H5: Validator must use real calendar days between trade and T+2 settlement."""

    def test_friday_trade_advance_uses_4_days(self):
        """Fri → Tue settlement = 4 calendar days, not 2."""
        model = TransactionCostModel(
            broker_profile=BrokerFeeProfile.custom(rate=0.0015, fee_includes_vat=False),
            tax_profile=TaxProfile(),
            vat_model=VAT_DISABLED,
            slippage_model=FixedBpsSlippageModel(bps=0.0),
        )
        advance = CashAdvanceModel(profile=CashAdvanceProfile(
            enabled=True, fee_model=FeeModel.DAILY_INTEREST,
            daily_rate=0.001, minimum_fee=0, vat_enabled=False,
        ))
        validator = RecommendationValidator(cost_model=model, cash_advance_model=advance)
        friday = datetime.date(2024, 1, 5)
        # T+2 settlement = Tuesday Jan 9 → 4 calendar days from Friday
        payload = RecommendationPayload(
            action="SELL", symbol="FPT", quantity=1000, price=100_000,
            trade_date=friday,
            settled_shares={"FPT": 1000},
            reference_price=100_000,
            exchange="HOSE",
            avg_daily_value_20d=50_000_000_000,
        )
        result = validator.validate(payload)
        # estimated_advance_fee should reflect 4 days, not 2
        # 100M * 0.001 * 4 = 400,000 VND (vs 200,000 if hardcoded 2)
        # Fee is on net_proceeds (slightly less than 100M after sell costs)
        # net_proceeds ≈ 100M - 150K brokerage - 100K sell_tax = 99,750,000
        # advance fee = 99,750,000 * 0.001 * 4 = 399,000
        assert result.estimated_advance_fee == pytest.approx(399_000, rel=0.01)


class TestH7_LotSizeDetectsFractional:
    """H7: check_lot_size must reject fractional floats (100.5)."""

    def test_fractional_float_rejected(self):
        result = check_lot_size(100.5, lot_size=100)
        assert result.passed is False
        assert RuleViolation.LOT_SIZE_VIOLATION in result.violations
        assert any("Fractional" in m or "fractional" in m for m in result.messages)

    def test_whole_float_still_works(self):
        """100.0 is whole and a lot multiple → passes."""
        result = check_lot_size(100.0, lot_size=100)
        assert result.passed is True

    def test_99_point_99_rejected(self):
        result = check_lot_size(99.99, lot_size=100)
        assert result.passed is False
