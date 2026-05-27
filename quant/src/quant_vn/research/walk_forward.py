"""Walk-forward analysis to test out-of-sample strategy performance."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import pandas as pd

from ..backtest.engine import BacktestEngine, BacktestResult
from ..market.costs import TransactionCosts, DEFAULT_COSTS
from ..strategies.base import AbstractStrategy, StrategyParams

logger = logging.getLogger(__name__)


@dataclass
class WalkForwardWindow:
    window_id: int
    in_sample_start: str
    in_sample_end: str
    out_of_sample_start: str
    out_of_sample_end: str
    in_sample_result: BacktestResult | None = None
    oos_result: BacktestResult | None = None

    def degradation_sharpe(self) -> float:
        """OOS Sharpe / IS Sharpe.

        NOTE: Meaningful only in a parameter walk-forward where IS parameters are
        re-optimized per window and then evaluated OOS. With fixed parameters (as in
        rolling_walk_forward), this ratio measures regime consistency between two
        consecutive time windows — not generalization. A value near 1.0 here means
        the two periods happened to have similar Sharpe ratios, not that the strategy
        generalizes well.
        """
        if self.in_sample_result is None or self.oos_result is None:
            return float("nan")
        is_sharpe = self.in_sample_result.metrics.get("sharpe", 0)
        oos_sharpe = self.oos_result.metrics.get("sharpe", 0)
        if is_sharpe == 0:
            return float("nan")
        return oos_sharpe / is_sharpe


@dataclass
class WalkForwardResult:
    windows: list[WalkForwardWindow]
    strategy_name: str
    symbol: str

    def summary(self) -> pd.DataFrame:
        rows = []
        for w in self.windows:
            row = {
                "window": w.window_id,
                "is_start": w.in_sample_start,
                "is_end": w.in_sample_end,
                "oos_start": w.out_of_sample_start,
                "oos_end": w.out_of_sample_end,
            }
            if w.in_sample_result:
                row["is_sharpe"] = w.in_sample_result.metrics.get("sharpe", float("nan"))
                row["is_cagr_pct"] = w.in_sample_result.metrics.get("cagr_pct", float("nan"))
                row["is_maxdd_pct"] = w.in_sample_result.metrics.get("max_drawdown_pct", float("nan"))
            if w.oos_result:
                row["oos_sharpe"] = w.oos_result.metrics.get("sharpe", float("nan"))
                row["oos_cagr_pct"] = w.oos_result.metrics.get("cagr_pct", float("nan"))
                row["oos_maxdd_pct"] = w.oos_result.metrics.get("max_drawdown_pct", float("nan"))
            row["sharpe_degradation"] = w.degradation_sharpe()
            rows.append(row)
        return pd.DataFrame(rows)


def walk_forward_split(
    prices: pd.DataFrame,
    in_sample_ratio: float = 0.7,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Simple single in-sample / out-of-sample split.

    Args:
        prices: Full price DataFrame with DatetimeIndex.
        in_sample_ratio: Fraction of data used for in-sample (default 70%).

    Returns:
        (in_sample_df, oos_df)

    Note: Always ensure the in-sample period ends BEFORE the OOS period starts.
    """
    n = len(prices)
    split_idx = int(n * in_sample_ratio)
    return prices.iloc[:split_idx], prices.iloc[split_idx:]


def rolling_walk_forward(
    strategy: AbstractStrategy,
    prices: pd.DataFrame,
    symbol: str,
    in_sample_months: int = 24,
    oos_months: int = 6,
    embargo_days: int = 5,
    initial_capital: float = 100_000_000,
    costs: TransactionCosts = DEFAULT_COSTS,
) -> WalkForwardResult:
    """
    Rolling walk-forward analysis.

    Creates multiple IS/OOS windows by sliding forward in time.
    Trains (backtests) on IS, evaluates on OOS.

    embargo_days: gap between IS end and OOS start to avoid microstructure leakage.

    NOTE: For a proper walk-forward, you'd re-optimize parameters on each IS window.
    This implementation evaluates the same fixed parameters across all windows.
    For parameter optimization per window, combine with parameter_sweep().
    """
    engine = BacktestEngine(costs=costs, initial_capital=initial_capital)

    prices.index = pd.to_datetime(prices.index)
    start = prices.index[0]
    end = prices.index[-1]

    windows: list[WalkForwardWindow] = []
    window_id = 1
    window_start = start

    while True:
        is_end = window_start + pd.DateOffset(months=in_sample_months)
        oos_start = is_end + pd.DateOffset(days=embargo_days)
        oos_end = oos_start + pd.DateOffset(months=oos_months)

        if oos_end > end:
            break

        is_prices = prices[window_start:is_end]
        oos_prices = prices[oos_start:oos_end]

        if len(is_prices) < 50 or len(oos_prices) < 10:
            break

        w = WalkForwardWindow(
            window_id=window_id,
            in_sample_start=str(window_start.date()),
            in_sample_end=str(is_end.date()),
            out_of_sample_start=str(oos_start.date()),
            out_of_sample_end=str(oos_end.date()),
        )

        try:
            w.in_sample_result = engine.run(strategy, is_prices, symbol=symbol)
            w.oos_result = engine.run(strategy, oos_prices, symbol=symbol)
        except Exception as e:
            logger.warning("Walk-forward window %d failed: %s", window_id, e)

        windows.append(w)
        window_start = oos_start
        window_id += 1

    result = WalkForwardResult(
        windows=windows,
        strategy_name=strategy.name,
        symbol=symbol,
    )

    logger.info(
        "Walk-forward: %d windows for %s %s",
        len(windows),
        strategy.name,
        symbol,
    )
    return result
