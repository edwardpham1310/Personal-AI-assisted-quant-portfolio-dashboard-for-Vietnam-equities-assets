"""
Tests for market/settlement.py and market/calendar.py.

Tests 4-6 from specification:
    Test 4: T+2 settlement for shares
    Test 5: Sell settlement (cash pending)
    Test 6: Weekend settlement (Friday buy → Monday T+2)
"""

import datetime
import pytest
from quant_vn.market.settlement import SettlementLedger, SettlementRule, AssetType, SETTLEMENT_DAYS
from quant_vn.market.calendar import add_trading_days, t2_settlement_date, is_trading_day


# ── Calendar tests ─────────────────────────────────────────────────────────────

class TestCalendar:
    def test_friday_t2_is_tuesday(self):
        """Test 6: Friday buy → T+2 is Tuesday (skip Saturday, Sunday)."""
        friday = datetime.date(2024, 1, 5)   # Friday
        settlement = t2_settlement_date(friday)
        assert settlement == datetime.date(2024, 1, 9)   # Tuesday

    def test_monday_t2_is_wednesday(self):
        monday = datetime.date(2024, 1, 8)
        settlement = t2_settlement_date(monday)
        assert settlement == datetime.date(2024, 1, 10)

    def test_weekdays_are_trading_days(self):
        assert is_trading_day(datetime.date(2024, 3, 4))  # Monday
        assert is_trading_day(datetime.date(2024, 3, 5))  # Tuesday

    def test_weekend_is_not_trading_day(self):
        assert not is_trading_day(datetime.date(2024, 3, 2))  # Saturday
        assert not is_trading_day(datetime.date(2024, 3, 3))  # Sunday

    def test_new_year_is_holiday(self):
        assert not is_trading_day(datetime.date(2024, 1, 1))

    def test_tet_2026_in_calendar(self):
        """Regression: Tet 2026 must be in the holiday table (was missing before fix)."""
        # Tet 2026 block: Feb 16-20
        assert not is_trading_day(datetime.date(2026, 2, 16))
        assert not is_trading_day(datetime.date(2026, 2, 17))

    def test_hung_kings_day_2024(self):
        """Hung Kings Day 2024 is April 18 (was correctly Apr 18 in 2024)."""
        assert not is_trading_day(datetime.date(2024, 4, 18))

    def test_hung_kings_day_2023_not_april_18(self):
        """Hung Kings Day 2023 was April 29, NOT April 18 — regression for fixed hardcode."""
        assert not is_trading_day(datetime.date(2023, 4, 29))   # correct date
        # April 18, 2023 should be a TRADING day (Hung Kings Day not on Apr 18 in 2023)
        assert is_trading_day(datetime.date(2023, 4, 18))

    def test_add_trading_days_positive(self):
        monday = datetime.date(2024, 1, 8)
        assert add_trading_days(monday, 2) == datetime.date(2024, 1, 10)

    def test_add_trading_days_skips_weekend(self):
        thursday = datetime.date(2024, 1, 4)
        assert add_trading_days(thursday, 2) == datetime.date(2024, 1, 8)


# ── Settlement rule tests ──────────────────────────────────────────────────────

class TestSettlementRule:
    def test_stock_settlement_t2(self):
        rule = SettlementRule(AssetType.STOCK, settlement_days=2)
        trade_date = datetime.date(2024, 1, 8)
        assert rule.settlement_date(trade_date) == datetime.date(2024, 1, 10)

    def test_settlement_days_mapping(self):
        assert SETTLEMENT_DAYS[AssetType.STOCK] == 2
        assert SETTLEMENT_DAYS[AssetType.ETF] == 2
        assert SETTLEMENT_DAYS[AssetType.BOND] == 1


# ── SettlementLedger tests ─────────────────────────────────────────────────────

class TestSettlementLedger:
    """Tests 4 and 5: T+2 share and cash settlement."""

    @pytest.fixture
    def ledger(self):
        ldr = SettlementLedger()
        ldr.set_initial_cash(100_000_000)
        return ldr

    def test_buy_shares_not_sellable_t0(self, ledger):
        """Test 4: Shares are NOT sellable on trade date (T+0)."""
        trade_date = datetime.date(2024, 1, 8)  # Monday
        settlement = t2_settlement_date(trade_date)
        ledger.record_buy(trade_date, "FPT", 1000, settlement)
        assert ledger.available_shares_on("FPT", trade_date) == 0

    def test_buy_shares_not_sellable_t1(self, ledger):
        """Shares are NOT sellable on T+1."""
        trade_date = datetime.date(2024, 1, 8)
        settlement = t2_settlement_date(trade_date)
        ledger.record_buy(trade_date, "FPT", 1000, settlement)
        t1 = datetime.date(2024, 1, 9)
        assert ledger.available_shares_on("FPT", t1) == 0

    def test_buy_shares_available_t2(self, ledger):
        """Test 4: Shares become available at T+2."""
        trade_date = datetime.date(2024, 1, 8)
        settlement = t2_settlement_date(trade_date)
        ledger.record_buy(trade_date, "FPT", 1000, settlement)
        ledger.advance_date(settlement)
        assert ledger.available_shares_on("FPT", settlement) == 1000

    def test_buy_friday_available_tuesday(self, ledger):
        """Test 6: Buy Friday → shares available Tuesday (T+2 skips weekend)."""
        friday = datetime.date(2024, 1, 5)
        settlement = t2_settlement_date(friday)  # should be Tuesday Jan 9
        assert settlement == datetime.date(2024, 1, 9)
        ledger.record_buy(friday, "FPT", 500, settlement)
        ledger.advance_date(settlement)
        assert ledger.available_shares_on("FPT", settlement) == 500

    def test_sell_cash_not_available_t0(self, ledger):
        """Test 5: Sell proceeds are pending on T+0."""
        trade_date = datetime.date(2024, 1, 8)
        settlement = t2_settlement_date(trade_date)
        ledger.deduct_settled_shares("FPT", 0)  # nothing to deduct initially
        ledger.add_settled_shares("FPT", 1000)
        ledger.deduct_settled_shares("FPT", 1000)
        ledger.record_sell(trade_date, "FPT", 1000, 45_000_000, 45_500_000, settlement)
        # cash must be in pending, not settled
        assert ledger.pending_cash_total() == pytest.approx(45_000_000, abs=1)

    def test_sell_cash_not_available_t1(self, ledger):
        """Pending sell proceeds are not in settled cash on T+1."""
        trade_date = datetime.date(2024, 1, 8)
        settlement = t2_settlement_date(trade_date)
        ledger.record_sell(trade_date, "FPT", 1000, 45_000_000, 45_500_000, settlement)
        t1 = datetime.date(2024, 1, 9)
        ledger.advance_date(t1)
        # pending_cash is not settled_cash
        assert ledger.available_cash_on(t1) == pytest.approx(100_000_000, abs=1)

    def test_sell_cash_available_t2(self, ledger):
        """Test 5: Sell proceeds become available at T+2."""
        trade_date = datetime.date(2024, 1, 8)
        settlement = t2_settlement_date(trade_date)
        ledger.record_sell(trade_date, "FPT", 1000, 45_000_000, 45_500_000, settlement)
        ledger.advance_date(settlement)
        assert ledger.available_cash_on(settlement) == pytest.approx(145_000_000, abs=1)

    def test_pending_cash_not_in_available_cash(self, ledger):
        """Test 14: Pending cash is NOT in available_cash before settlement."""
        trade_date = datetime.date(2024, 1, 8)
        settlement = t2_settlement_date(trade_date)
        ledger.record_sell(trade_date, "FPT", 1000, 45_000_000, 45_500_000, settlement)
        # Before settlement date
        t1 = datetime.date(2024, 1, 9)
        available = ledger.available_cash_on(t1)
        pending = ledger.pending_cash_total()
        # Available must NOT include pending
        assert available == pytest.approx(100_000_000, abs=1)
        assert pending == pytest.approx(45_000_000, abs=1)

    def test_multiple_buys_accumulate(self, ledger):
        """Multiple buys of same symbol on same day accumulate at T+2."""
        trade_date = datetime.date(2024, 1, 8)
        settlement = t2_settlement_date(trade_date)
        ledger.record_buy(trade_date, "FPT", 500, settlement)
        ledger.record_buy(trade_date, "FPT", 300, settlement)
        ledger.advance_date(settlement)
        assert ledger.available_shares_on("FPT", settlement) == 800

    def test_sell_before_settlement_rejected(self, ledger):
        """Sell before shares settle → available_shares = 0, so rules reject it."""
        trade_date = datetime.date(2024, 1, 8)
        settlement = t2_settlement_date(trade_date)
        ledger.record_buy(trade_date, "FPT", 1000, settlement)
        t1 = datetime.date(2024, 1, 9)
        # Shares not yet settled
        assert ledger.available_shares_on("FPT", t1) == 0

    def test_cash_advance_no_double_count(self, ledger):
        """Test 16: After advance, settlement does NOT add cash again."""
        trade_date = datetime.date(2024, 1, 8)
        settlement = t2_settlement_date(trade_date)
        entry_id = ledger.record_sell(
            trade_date, "FPT", 1000, 45_000_000, 45_500_000, settlement
        )
        # Apply advance: credit 43M immediately
        ledger.apply_cash_advance(entry_id, advance_net_cash=43_000_000, advance_fee=2_000_000)
        cash_after_advance = ledger.available_cash_on(trade_date)
        # settled_cash should now include 43M advance
        assert cash_after_advance == pytest.approx(143_000_000, abs=1)

        # At settlement date: ADVANCED entry must NOT add another 45M
        ledger.advance_date(settlement)
        cash_at_settlement = ledger.available_cash_on(settlement)
        # Should still be 143M (no new cash added for the ADVANCED entry)
        assert cash_at_settlement == pytest.approx(143_000_000, abs=1)
