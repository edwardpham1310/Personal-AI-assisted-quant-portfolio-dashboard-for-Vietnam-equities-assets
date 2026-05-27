"""Experiment tracking: run a backtest and record its results."""

from __future__ import annotations

import datetime
import logging
from dataclasses import dataclass, field as dc_field
from typing import Optional

import pandas as pd

from ..backtest.engine import BacktestEngine, BacktestResult
from ..backtest.metrics import format_metrics_table
from ..market.costs import TransactionCosts, DEFAULT_COSTS
from ..strategies.base import AbstractStrategy

logger = logging.getLogger(__name__)


@dataclass
class ExperimentConfig:
    strategy: AbstractStrategy
    symbol: str
    start_date: str
    end_date: str
    initial_capital: float = 100_000_000
    costs: TransactionCosts = dc_field(default_factory=lambda: DEFAULT_COSTS)
    label: str = ""


def run_experiment(
    config: ExperimentConfig,
    prices: pd.DataFrame,
) -> BacktestResult:
    """Run a single experiment and return results."""
    engine = BacktestEngine(
        costs=config.costs,
        initial_capital=config.initial_capital,
    )
    result = engine.run(config.strategy, prices, symbol=config.symbol)
    logger.info(
        "Experiment [%s] %s on %s: CAGR=%.1f%% Sharpe=%.2f MaxDD=%.1f%%",
        config.label or config.strategy.name,
        config.strategy.describe(),
        config.symbol,
        result.metrics.get("cagr_pct", 0),
        result.metrics.get("sharpe", 0),
        result.metrics.get("max_drawdown_pct", 0),
    )
    return result


def compare_strategies(
    strategies: list[AbstractStrategy],
    prices: pd.DataFrame,
    symbol: str,
    start_date: str,
    end_date: str,
    initial_capital: float = 100_000_000,
    costs: TransactionCosts = DEFAULT_COSTS,
) -> pd.DataFrame:
    """
    Run multiple strategies on the same price series and return a comparison DataFrame.
    Rows = strategies, Columns = key metrics.
    """
    rows = []
    for strategy in strategies:
        config = ExperimentConfig(
            strategy=strategy,
            symbol=symbol,
            start_date=start_date,
            end_date=end_date,
            initial_capital=initial_capital,
            costs=costs,
        )
        result = run_experiment(config, prices)
        row = {"strategy": strategy.describe()}
        key_metrics = [
            "total_return_pct", "cagr_pct", "annualized_volatility_pct",
            "max_drawdown_pct", "sharpe", "sortino", "calmar",
            "n_trades", "win_rate_pct", "profit_factor", "avg_holding_days",
        ]
        for k in key_metrics:
            row[k] = result.metrics.get(k, float("nan"))
        rows.append(row)

    df = pd.DataFrame(rows)
    df = df.sort_values("sharpe", ascending=False)
    return df
