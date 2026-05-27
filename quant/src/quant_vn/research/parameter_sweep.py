"""Parameter sweep for strategy optimization.

WARNING: In-sample optimization is subject to overfitting.
Best parameters found here may not generalize to out-of-sample data.
Always validate results using walk_forward.py before acting on them.
"""

from __future__ import annotations

import itertools
import logging
from typing import Any

import pandas as pd

from ..backtest.engine import BacktestEngine
from ..market.costs import TransactionCosts, DEFAULT_COSTS
from ..strategies.base import AbstractStrategy, StrategyParams

logger = logging.getLogger(__name__)


def parameter_sweep(
    strategy_class: type[AbstractStrategy],
    params_class: type[StrategyParams],
    param_grid: dict[str, list[Any]],
    prices: pd.DataFrame,
    symbol: str,
    initial_capital: float = 100_000_000,
    costs: TransactionCosts = DEFAULT_COSTS,
    sort_by: str = "sharpe",
) -> pd.DataFrame:
    """
    Exhaustive grid search over strategy parameters.

    WARNING: Results are in-sample only. See walk_forward.py for proper validation.

    Args:
        strategy_class: Strategy class (e.g., MovingAverageCrossStrategy)
        params_class: Params dataclass (e.g., MACrossParams)
        param_grid: dict of param_name → list of values to try
                    e.g. {"fast_window": [5, 10, 20], "slow_window": [50, 100]}
        prices: Price DataFrame (DatetimeIndex, OHLCV columns)
        symbol: Ticker symbol label
        initial_capital: Starting capital
        costs: Transaction cost model
        sort_by: Metric to sort results by (default: "sharpe")

    Returns:
        DataFrame sorted by sort_by metric descending.
        Includes all parameter combinations and key performance metrics.

    NOTE: Best in-sample parameters are almost certainly overfit.
    Use the results to narrow down a smaller search space for walk-forward testing.
    """
    engine = BacktestEngine(costs=costs, initial_capital=initial_capital)

    # Generate all parameter combinations
    keys = list(param_grid.keys())
    values = list(param_grid.values())
    combinations = list(itertools.product(*values))
    total = len(combinations)
    logger.info("Parameter sweep: %d combinations for %s", total, symbol)

    rows = []
    for i, combo in enumerate(combinations):
        param_dict = dict(zip(keys, combo))
        try:
            params = params_class(**param_dict)
            strategy = strategy_class(params)
            strategy.validate_params()
            result = engine.run(strategy, prices, symbol=symbol)

            row = dict(param_dict)
            key_metrics = [
                "total_return_pct", "cagr_pct", "annualized_volatility_pct",
                "max_drawdown_pct", "sharpe", "sortino", "calmar",
                "n_trades", "win_rate_pct", "profit_factor",
                "avg_holding_days", "exposure_time_pct",
            ]
            for k in key_metrics:
                row[k] = result.metrics.get(k, float("nan"))

            rows.append(row)

            if (i + 1) % 50 == 0:
                logger.info("  Sweep progress: %d/%d", i + 1, total)

        except (ValueError, TypeError) as e:
            logger.debug("Skipped params %s: %s", param_dict, e)
            continue

    if not rows:
        logger.warning("No valid parameter combinations found.")
        return pd.DataFrame()

    df = pd.DataFrame(rows)
    if sort_by in df.columns:
        df = df.sort_values(sort_by, ascending=False)

    _print_sweep_warning(total, sort_by)
    return df.reset_index(drop=True)


def _print_sweep_warning(n_combinations: int, sort_by: str) -> None:
    warning = (
        "\n⚠️  OVERFITTING WARNING ⚠️\n"
        f"  Tested {n_combinations} parameter combinations in-sample.\n"
        f"  Best '{sort_by}' parameters are optimized for this specific historical period.\n"
        "  In-sample results are NOT a reliable predictor of future performance.\n"
        "  ALWAYS validate with walk-forward testing before using any parameters.\n"
        "  See: research/walk_forward.py\n"
    )
    print(warning)
    logger.warning(warning)
