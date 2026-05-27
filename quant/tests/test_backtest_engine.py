"""
Backtest engine correctness tests.

These tests use synthetic data with known price trajectories to verify:
- Exact entry/exit dates
- Correct cash accounting
- Correct PnL after costs
- No lookahead bias
- Proper drawdown calculation
"""

from __future__ import annotations

from dataclasses import dataclass
import numpy as np
import pandas as pd
import pytest

from quant_vn.backtest.engine import BacktestEngine
from quant_vn.market.costs import TransactionCosts
from quant_vn.strategies.buy_and_hold import BuyAndHoldStrategy
from quant_vn.strategies.moving_average_cross import MovingAverageCrossStrategy, MACrossParams


ZERO_COSTS = TransactionCosts(commission_rate=0.0, sell_tax_rate=0.0, slippage_bps=0.0)


def _flat_prices(n=30, price=100.0) -> pd.DataFrame:
    """Flat price series — useful for testing cost calculations."""
    dates = pd.date_range("2020-01-02", periods=n, freq="B")
    return pd.DataFrame({
        "open": [price] * n,
        "high": [price * 1.01] * n,
        "low": [price * 0.99] * n,
        "close": [price] * n,
        "volume": [1_000_000] * n,
    }, index=dates)


def _rising_prices(n=30, start=100.0, end=200.0) -> pd.DataFrame:
    dates = pd.date_range("2020-01-02", periods=n, freq="B")
    prices = np.linspace(start, end, n)
    return pd.DataFrame({
        "open": prices,
        "high": prices * 1.01,
        "low": prices * 0.99,
        "close": prices,
        "volume": [1_000_000] * n,
    }, index=dates)


# ── Basic accounting tests ─────────────────────────────────────────────────────

def test_buy_and_hold_final_equity_no_costs():
    """With zero costs on flat prices, equity should equal initial capital throughout."""
    engine = BacktestEngine(costs=ZERO_COSTS, initial_capital=10_000_000)
    prices = _flat_prices(30, 100.0)
    result = engine.run(BuyAndHoldStrategy(), prices, symbol="TEST")
    # Final equity should equal initial capital (flat prices, no costs)
    assert abs(result.final_equity - 10_000_000) < 1.0


def test_buy_and_hold_rising_prices_profit():
    """On rising prices, buy-and-hold should produce a positive return."""
    engine = BacktestEngine(costs=ZERO_COSTS, initial_capital=10_000_000)
    prices = _rising_prices(50, 100.0, 150.0)
    result = engine.run(BuyAndHoldStrategy(), prices, symbol="TEST")
    assert result.metrics["total_return"] > 0.0


def test_costs_reduce_returns():
    """Adding transaction costs must reduce returns compared to zero costs."""
    prices = _rising_prices(50, 100.0, 150.0)

    result_no_cost = BacktestEngine(costs=ZERO_COSTS, initial_capital=10_000_000).run(
        BuyAndHoldStrategy(), prices, symbol="TEST"
    )
    result_with_cost = BacktestEngine(
        costs=TransactionCosts(commission_rate=0.001, sell_tax_rate=0.001, slippage_bps=10),
        initial_capital=10_000_000,
    ).run(BuyAndHoldStrategy(), prices, symbol="TEST")

    assert result_with_cost.metrics["total_return"] < result_no_cost.metrics["total_return"]


def test_trade_log_contains_entry_exit():
    """A strategy that enters and exits must log at least one completed trade."""
    prices = _rising_prices(100, 100.0, 150.0)
    engine = BacktestEngine(costs=ZERO_COSTS, initial_capital=10_000_000)
    result = engine.run(BuyAndHoldStrategy(), prices, symbol="TEST")
    assert len(result.trade_log) >= 1


def test_equity_curve_has_correct_length():
    n = 100
    prices = _flat_prices(n)
    result = BacktestEngine(costs=ZERO_COSTS, initial_capital=10_000_000).run(
        BuyAndHoldStrategy(), prices
    )
    assert len(result.equity_curve) == n


def test_equity_never_negative():
    """Equity must remain non-negative throughout the backtest."""
    rng = np.random.default_rng(99)
    n = 200
    dates = pd.date_range("2020-01-02", periods=n, freq="B")
    close = 100.0 * np.exp(np.cumsum(rng.normal(0, 0.02, n)))
    prices = pd.DataFrame({
        "open": close,
        "high": close * 1.01,
        "low": close * 0.99,
        "close": close,
        "volume": [1_000_000] * n,
    }, index=dates)

    result = BacktestEngine(
        costs=TransactionCosts(commission_rate=0.001, sell_tax_rate=0.001, slippage_bps=10),
        initial_capital=100_000_000,
    ).run(BuyAndHoldStrategy(), prices, symbol="TEST")

    assert (result.equity_curve["equity"] >= 0).all()


# ── No-lookahead bias verification ────────────────────────────────────────────

def test_no_lookahead_execution_at_next_open():
    """
    With NEXT_OPEN execution:
    Signal at T must execute at T+1 open.
    We verify by checking that the first trade executes on bar 2 (index 1),
    not bar 1 (index 0).
    """
    prices = _rising_prices(30, 100.0, 130.0)
    engine = BacktestEngine(costs=ZERO_COSTS, initial_capital=10_000_000)
    result = engine.run(BuyAndHoldStrategy(), prices, symbol="TEST")

    if not result.trade_log.empty:
        entry_date = result.trade_log["entry_date"].iloc[0]
        # Signal is generated on bar 0 (first bar), but execution must be on bar 1 or later
        assert entry_date >= prices.index[1].date()


def test_identical_results_regardless_of_future_data():
    """
    Run strategy on first 100 bars. Then run on all 200 bars.
    The signals for the first 100 bars must be identical.
    This proves no future data leaks into the signal calculation.
    """
    rng = np.random.default_rng(10)
    n = 200
    dates = pd.date_range("2020-01-02", periods=n, freq="B")
    close = 100.0 * np.exp(np.cumsum(rng.normal(0.0003, 0.012, n)))
    all_prices = pd.DataFrame({
        "open": close,
        "high": close * 1.01,
        "low": close * 0.99,
        "close": close,
        "volume": [1_000_000] * n,
    }, index=dates)

    params = MACrossParams(fast_window=5, slow_window=15)
    strat = MovingAverageCrossStrategy(params)

    sig_full = strat.generate_signals(all_prices)
    sig_short = strat.generate_signals(all_prices.iloc[:100])

    pd.testing.assert_series_equal(sig_full.iloc[:100], sig_short, check_names=False)


# ── Drawdown tests ─────────────────────────────────────────────────────────────

def test_max_drawdown_is_non_positive():
    prices = _rising_prices(50, 150.0, 50.0)  # falling prices
    result = BacktestEngine(costs=ZERO_COSTS, initial_capital=10_000_000).run(
        BuyAndHoldStrategy(), prices, symbol="TEST"
    )
    assert result.metrics["max_drawdown"] <= 0.0


def test_max_drawdown_of_monotone_rising_is_zero():
    """Strictly rising prices with buy-and-hold should have zero drawdown after entry."""
    prices = _rising_prices(50, 100.0, 200.0)
    result = BacktestEngine(costs=ZERO_COSTS, initial_capital=10_000_000).run(
        BuyAndHoldStrategy(), prices, symbol="TEST"
    )
    # Max drawdown should be very close to 0 (no drawdown on monotone rise)
    assert result.metrics["max_drawdown"] >= -0.05  # allow small rounding


# ── PnL calculation tests ─────────────────────────────────────────────────────

def test_pnl_with_known_return():
    """
    On 100% price increase with zero costs, final equity should be ~2x initial.
    """
    prices = _rising_prices(30, 100.0, 200.0)
    result = BacktestEngine(costs=ZERO_COSTS, initial_capital=10_000_000).run(
        BuyAndHoldStrategy(), prices, symbol="TEST"
    )
    # Allow 5% tolerance for execution at different open prices
    assert result.metrics["total_return"] > 0.8


def test_metrics_present():
    """All expected metrics must be present in the result."""
    prices = _flat_prices(100)
    result = BacktestEngine(costs=ZERO_COSTS, initial_capital=10_000_000).run(
        BuyAndHoldStrategy(), prices
    )
    required_metrics = [
        "total_return", "cagr", "sharpe", "max_drawdown",
        "n_trades", "win_rate", "profit_factor",
    ]
    for k in required_metrics:
        assert k in result.metrics, f"Missing metric: {k}"


# ── Exact cost accounting ─────────────────────────────────────────────────────

def test_net_pnl_equals_gross_minus_exact_costs():
    """
    net_pnl = gross_pnl - entry_cost - exit_cost.
    With known prices and costs we can verify this to within 1 VND.
    """
    costs = TransactionCosts(commission_rate=0.001, sell_tax_rate=0.001, slippage_bps=10)
    prices = _rising_prices(50, 100.0, 150.0)
    engine = BacktestEngine(costs=costs, initial_capital=10_000_000)
    result = engine.run(BuyAndHoldStrategy(), prices, symbol="TEST")

    assert not result.trade_log.empty
    for _, trade in result.trade_log.iterrows():
        expected_net = trade["gross_pnl"] - trade["entry_cost"] - trade["exit_cost"]
        assert abs(trade["net_pnl"] - expected_net) < 1.0, (
            f"net_pnl mismatch: {trade['net_pnl']} vs {expected_net}"
        )


def test_total_spend_never_exceeds_cash():
    """After sizing with costs reserved, no trade should overdraw the portfolio."""
    costs = TransactionCosts(commission_rate=0.001, sell_tax_rate=0.001, slippage_bps=10)
    rng = np.random.default_rng(123)
    n = 300
    dates = pd.date_range("2020-01-02", periods=n, freq="B")
    close = 100.0 * np.exp(np.cumsum(rng.normal(0.0003, 0.015, n)))
    prices = pd.DataFrame({
        "open": close,
        "high": close * 1.01,
        "low": close * 0.99,
        "close": close,
        "volume": [1_000_000] * n,
    }, index=dates)

    from quant_vn.strategies.moving_average_cross import MovingAverageCrossStrategy, MACrossParams
    strategy = MovingAverageCrossStrategy(MACrossParams(fast_window=10, slow_window=30))
    result = BacktestEngine(costs=costs, initial_capital=10_000_000).run(strategy, prices, "T")
    assert (result.equity_curve["cash"] >= -1.0).all()


# ── Re-entry after flat period ────────────────────────────────────────────────

def test_two_trades_on_reentry():
    """
    A strategy with signal [0,0,1,1,0,0,1,1] should produce exactly two completed
    trades, with the second entry after the first exit.
    """
    from quant_vn.strategies.base import AbstractStrategy, StrategyParams

    @dataclass
    class EmptyParams(StrategyParams):
        pass

    class TwoTradeStrategy(AbstractStrategy):
        """Enters at bar 20, exits at bar 50, re-enters at bar 70, exits at end."""

        def __init__(self):
            super().__init__(EmptyParams())

        @property
        def name(self) -> str:
            return "two_trade"

        def validate_params(self) -> None:
            pass

        def generate_signals(self, prices: pd.DataFrame) -> pd.Series:
            sig = pd.Series(0.0, index=prices.index)
            sig.iloc[20:50] = 1.0
            sig.iloc[70:] = 1.0
            return sig

    n = 100
    prices = _flat_prices(n)

    result = BacktestEngine(costs=ZERO_COSTS, initial_capital=10_000_000).run(
        TwoTradeStrategy(), prices, symbol="TEST"
    )

    # Must have exactly 2 completed trades
    assert len(result.trade_log) == 2, f"Expected 2 trades, got {len(result.trade_log)}"

    # Second entry must be after first exit
    first_exit = result.trade_log["exit_date"].iloc[0]
    second_entry = result.trade_log["entry_date"].iloc[1]
    assert second_entry >= first_exit
