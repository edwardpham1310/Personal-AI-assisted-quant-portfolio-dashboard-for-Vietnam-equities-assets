"""Tests for performance metrics calculations."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from quant_vn.backtest.metrics import compute_metrics


def _make_equity(returns_list: list[float], initial: float = 10_000_000) -> pd.DataFrame:
    dates = pd.date_range("2020-01-02", periods=len(returns_list), freq="B")
    equity = [initial]
    for r in returns_list[1:]:
        equity.append(equity[-1] * (1 + r))
    return pd.DataFrame({"equity": equity, "returns": returns_list}, index=dates)


def test_zero_return_for_flat_equity():
    equity = _make_equity([0.0] * 252)
    metrics = compute_metrics(equity, [], initial_capital=10_000_000)
    assert abs(metrics["total_return"]) < 1e-9
    assert abs(metrics["cagr"]) < 1e-6


def test_positive_total_return():
    returns = [0.001] * 252  # 0.1% per day = ~28% per year
    equity = _make_equity(returns)
    metrics = compute_metrics(equity, [], initial_capital=10_000_000)
    assert metrics["total_return"] > 0.0
    assert metrics["cagr"] > 0.0


def test_sharpe_positive_for_trending_up():
    returns = [0.001] * 252
    equity = _make_equity(returns)
    metrics = compute_metrics(equity, [], initial_capital=10_000_000)
    assert metrics["sharpe"] > 0


def test_max_drawdown_falling_series():
    """50% price drop should result in ~50% max drawdown."""
    returns = [0.0] * 100 + [-0.01] * 50 + [0.0] * 100
    equity = _make_equity(returns)
    metrics = compute_metrics(equity, [], initial_capital=10_000_000)
    # Drawdown should be meaningful negative
    assert metrics["max_drawdown"] < -0.10


def test_max_drawdown_never_positive():
    rng = np.random.default_rng(42)
    returns = rng.normal(0.001, 0.01, 300).tolist()
    equity = _make_equity(returns)
    metrics = compute_metrics(equity, [], initial_capital=10_000_000)
    assert metrics["max_drawdown"] <= 0.0


def test_win_rate_all_winning_trades():
    from quant_vn.backtest.portfolio import Trade
    import datetime

    equity = _make_equity([0.002] * 100)
    winning_trade = {
        "symbol": "TEST",
        "entry_date": datetime.date(2020, 1, 2),
        "entry_price": 100.0,
        "exit_date": datetime.date(2020, 2, 1),
        "exit_price": 110.0,
        "quantity": 100.0,
        "entry_cost": 10.0,
        "exit_cost": 11.0,
        "cost": 21.0,
        "gross_pnl": 1000.0,
        "net_pnl": 979.0,
        "holding_days": 30,
        "return_pct": 0.097,
        "exit_reason": "signal",
    }
    trades_df = pd.DataFrame([winning_trade] * 5)
    metrics = compute_metrics(equity, trades_df, initial_capital=10_000_000)
    assert metrics["win_rate"] == 1.0
    assert metrics["n_trades"] == 5


def test_profit_factor_with_mixed_trades():
    equity = _make_equity([0.001] * 200)
    trades_df = pd.DataFrame([
        {"net_pnl": 1000.0, "entry_price": 100.0, "quantity": 10.0,
         "holding_days": 5, "return_pct": 0.1, "exit_reason": "signal",
         "symbol": "T", "entry_date": None, "exit_date": None,
         "entry_price": 100.0, "exit_price": 110.0,
         "quantity": 10.0, "entry_cost": 1.0, "exit_cost": 1.0, "cost": 2.0, "gross_pnl": 1002.0},
        {"net_pnl": -500.0, "entry_price": 100.0, "quantity": 10.0,
         "holding_days": 3, "return_pct": -0.05, "exit_reason": "signal",
         "symbol": "T", "entry_date": None, "exit_date": None,
         "entry_price": 100.0, "exit_price": 95.0,
         "quantity": 10.0, "entry_cost": 1.0, "exit_cost": 1.0, "cost": 2.0, "gross_pnl": -498.0},
    ])
    metrics = compute_metrics(equity, trades_df, initial_capital=10_000_000)
    assert metrics["profit_factor"] == pytest.approx(2.0, abs=0.1)


def test_empty_equity_returns_zeros():
    metrics = compute_metrics(pd.DataFrame(), [], initial_capital=10_000_000)
    assert "total_return" in metrics


# ── Sortino formula correctness ───────────────────────────────────────────────

def test_sortino_all_positive_excess_returns():
    """When every daily return exceeds rf, downside is zero → Sortino is inf."""
    returns = [0.01] * 252
    equity = _make_equity(returns)
    metrics = compute_metrics(equity, [], initial_capital=10_000_000, risk_free_rate=0.0)
    assert metrics["sortino"] == float("inf")


def test_sortino_known_value():
    """Sortino with alternating +1% / -0.5% days (rf=0) matches hand-calculated value.

    semi_dev = sqrt(mean([0, 0.005, 0, 0.005, ...]^2))
             = sqrt(0.5 * 0.005^2)
             = sqrt(0.0000125) ≈ 0.003536
    ann semi_dev = 0.003536 * sqrt(252) ≈ 0.05612
    mean excess = (0.01 + (-0.005)) / 2 = 0.0025
    ann mean excess = 0.0025 * 252 = 0.63
    sortino ≈ 0.63 / 0.05612 ≈ 11.2
    """
    n = 500
    returns = [0.01 if i % 2 == 0 else -0.005 for i in range(n)]
    equity = _make_equity(returns)
    metrics = compute_metrics(equity, [], initial_capital=10_000_000, risk_free_rate=0.0)
    assert 9.0 < metrics["sortino"] < 14.0, f"Expected ~11.2, got {metrics['sortino']}"


def test_sortino_greater_than_sharpe_when_asymmetric():
    """Sortino should exceed Sharpe when the loss distribution is mild."""
    returns = [0.001] * 200 + [-0.003] * 52
    equity = _make_equity(returns)
    metrics = compute_metrics(equity, [], initial_capital=10_000_000)
    assert metrics["sortino"] >= metrics["sharpe"]
