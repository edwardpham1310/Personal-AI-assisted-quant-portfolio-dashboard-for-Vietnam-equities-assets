"""
Vectorized backtest engine for daily OHLCV data.

Lookahead-bias prevention:
- Signals are generated using only data up to bar T
- Execution happens at the OPEN of bar T+1 (next_open mode, default)
- The engine shifts signals by 1 bar before computing trades:
      positions = signals.shift(1)
- Never uses future prices for any calculation

Vietnam-specific handling:
- T+2 settlement tracked but not enforced in MVP (document as known limitation)
- Long-only by default
- Transaction costs: commission + sell tax + slippage applied to every trade
"""

from __future__ import annotations

import datetime
import logging
from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd

from ..market.costs import TransactionCosts, DEFAULT_COSTS
from ..strategies.base import AbstractStrategy
from .execution import ExecutionConfig, ExecutionMode
from .portfolio import PortfolioState, Trade

logger = logging.getLogger(__name__)


@dataclass
class BacktestResult:
    """Complete result of a single backtest run."""

    strategy_name: str
    symbol: str
    start_date: datetime.date
    end_date: datetime.date
    initial_capital: float
    equity_curve: pd.DataFrame    # date-indexed: equity, cash, position_value, drawdown, returns
    trade_log: pd.DataFrame       # one row per completed trade
    metrics: dict
    params: dict

    @property
    def final_equity(self) -> float:
        if self.equity_curve.empty:
            return self.initial_capital
        return float(self.equity_curve["equity"].iloc[-1])

    @property
    def total_return(self) -> float:
        return (self.final_equity - self.initial_capital) / self.initial_capital


class BacktestEngine:
    """
    Vectorized single-symbol backtest engine.

    Usage:
        engine = BacktestEngine(costs=DEFAULT_COSTS)
        result = engine.run(strategy, prices_df, symbol="FPT")
    """

    def __init__(
        self,
        costs: TransactionCosts = DEFAULT_COSTS,
        initial_capital: float = 100_000_000,
        execution: ExecutionConfig | None = None,
        annual_trading_days: int = 252,
    ):
        self.costs = costs
        self.initial_capital = initial_capital
        self.execution = execution or ExecutionConfig()
        self.annual_trading_days = annual_trading_days

    def run(
        self,
        strategy: AbstractStrategy,
        prices: pd.DataFrame,
        symbol: str = "",
    ) -> BacktestResult:
        """
        Run a backtest for one strategy on one symbol's price data.

        Args:
            strategy: An AbstractStrategy instance.
            prices: DataFrame with DatetimeIndex, columns: open, high, low, close, volume.
            symbol: Ticker symbol (for labelling only).

        Returns:
            BacktestResult with equity curve, trade log, and metrics.
        """
        prices = self._validate_and_prepare(prices)
        if prices.empty:
            raise ValueError(f"Price data for {symbol} is empty after preparation.")

        # 1. Generate signals (T uses data 0..T only)
        raw_signals = strategy.generate_signals(prices)
        raw_signals = raw_signals.fillna(0.0)

        # 2. Determine execution prices based on mode
        # NEXT_OPEN (default): signal at T → execute at T+1 open
        # This shift is the core no-lookahead guarantee
        if self.execution.mode == ExecutionMode.NEXT_OPEN:
            exec_prices = prices["open"].copy()
            # shift signals forward by 1: position[T] = signal[T-1]
            positions = raw_signals.shift(1).fillna(0.0)
        elif self.execution.mode == ExecutionMode.NEXT_CLOSE:
            exec_prices = prices["close"].copy()
            positions = raw_signals.shift(1).fillna(0.0)
        else:  # SAME_CLOSE — academic only, warn
            logger.warning(
                "ExecutionMode.SAME_CLOSE uses close price on signal day — "
                "this introduces minor lookahead and is only for academic comparison."
            )
            exec_prices = prices["close"].copy()
            positions = raw_signals.copy()

        # 3. Determine trade events (position changes).
        # Bar 0 is always flat after shift(1)+fillna(0), so fillna(0.0) is correct.
        pos_changes = positions.diff().fillna(0.0)

        # 4. Simulate trades
        trade_log, equity_rows = self._simulate(
            prices=prices,
            positions=positions,
            pos_changes=pos_changes,
            exec_prices=exec_prices,
            symbol=symbol,
        )

        # 5. Build equity curve
        equity_df = self._build_equity_curve(equity_rows)

        # 6. Compute metrics
        from ..backtest.metrics import compute_metrics
        metrics = compute_metrics(
            equity_df,
            trade_log,
            initial_capital=self.initial_capital,
            annual_trading_days=self.annual_trading_days,
        )

        start_date = prices.index[0].date() if hasattr(prices.index[0], "date") else prices.index[0]
        end_date = prices.index[-1].date() if hasattr(prices.index[-1], "date") else prices.index[-1]

        return BacktestResult(
            strategy_name=strategy.name,
            symbol=symbol,
            start_date=start_date,
            end_date=end_date,
            initial_capital=self.initial_capital,
            equity_curve=equity_df,
            trade_log=pd.DataFrame([t.to_dict() for t in trade_log]),
            metrics=metrics,
            params=strategy.params.to_dict(),
        )

    def _validate_and_prepare(self, prices: pd.DataFrame) -> pd.DataFrame:
        required = {"open", "high", "low", "close"}
        missing = required - set(prices.columns)
        if missing:
            raise ValueError(f"Prices DataFrame missing columns: {missing}")

        prices = prices.copy()
        prices.index = pd.to_datetime(prices.index)
        prices = prices.sort_index()

        # Drop rows with null prices
        prices = prices.dropna(subset=list(required))
        return prices

    def _simulate(
        self,
        prices: pd.DataFrame,
        positions: pd.Series,
        pos_changes: pd.Series,
        exec_prices: pd.Series,
        symbol: str,
    ) -> tuple[list[Trade], list[dict]]:
        """
        Step through each bar and simulate position changes with transaction costs.
        Returns (completed_trades, equity_daily_records).
        """
        portfolio = PortfolioState(initial_capital=self.initial_capital)
        completed_trades: list[Trade] = []
        equity_rows: list[dict] = []

        for i, (ts, row) in enumerate(prices.iterrows()):
            date = ts.date() if hasattr(ts, "date") else ts
            current_price = float(exec_prices.iloc[i])
            close_price = float(row["close"])

            # Use close price for marking positions to market
            current_prices_map = {symbol: close_price} if symbol in portfolio.positions else {}

            pos_target = float(positions.iloc[i])
            change = float(pos_changes.iloc[i])

            # Entering a long position
            if change > 0 and pos_target > 0 and symbol not in portfolio.positions:
                if current_price > 0:
                    qty = self.execution.compute_quantity(
                        available_cash=portfolio.cash,
                        current_equity=portfolio.equity({symbol: close_price}),
                        price=current_price,
                        costs=self.costs,
                    )
                    entry_cost = self.costs.buy_cost(current_price * qty)
                    portfolio.open_position(symbol, date, current_price, qty, entry_cost)

            # Exiting a long position
            elif change < 0 and symbol in portfolio.positions:
                if current_price > 0:
                    exit_cost = self.costs.sell_cost(
                        current_price * portfolio.positions[symbol].quantity
                    )
                    trade = portfolio.close_position(symbol, date, current_price, exit_cost, "signal")
                    if trade:
                        completed_trades.append(trade)

            # Record daily equity
            price_map = {symbol: close_price} if symbol in portfolio.positions else {}
            portfolio.record_equity(date, price_map)
            eq = portfolio.equity(price_map)
            equity_rows.append({
                "date": date,
                "equity": eq,
                "cash": portfolio.cash,
                "position_value": portfolio.market_value(price_map),
            })

        # Close any open position at the last bar's close
        if symbol in portfolio.positions:
            last_close = float(prices["close"].iloc[-1])
            last_date = prices.index[-1].date() if hasattr(prices.index[-1], "date") else prices.index[-1]
            exit_cost = self.costs.sell_cost(last_close * portfolio.positions[symbol].quantity)
            trade = portfolio.close_position(symbol, last_date, last_close, exit_cost, "end_of_period")
            if trade:
                completed_trades.append(trade)

        return completed_trades, equity_rows

    def _build_equity_curve(self, equity_rows: list[dict]) -> pd.DataFrame:
        if not equity_rows:
            return pd.DataFrame()

        df = pd.DataFrame(equity_rows)
        df["date"] = pd.to_datetime(df["date"])
        df = df.set_index("date").sort_index()

        df["returns"] = df["equity"].pct_change().fillna(0.0)

        # Drawdown
        rolling_max = df["equity"].cummax()
        df["drawdown"] = (df["equity"] - rolling_max) / rolling_max

        return df
