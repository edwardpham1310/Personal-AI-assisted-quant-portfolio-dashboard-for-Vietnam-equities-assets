"""
Example: Backtest MA crossover and RSI mean reversion on FPT.

This script demonstrates:
1. Loading CSV data (or generating synthetic data as fallback)
2. Running 3 strategies on one symbol
3. Comparing results
4. Generating HTML report

Usage:
    # With real data:
    python examples/run_backtest_fpt.py

    # The script auto-generates synthetic FPT-like data if no real data exists.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Add project source to path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import numpy as np
import pandas as pd

from quant_vn.backtest.engine import BacktestEngine
from quant_vn.backtest.reports import print_report, save_csv_report
from quant_vn.config.settings import settings
from quant_vn.data.storage import Database, PriceRepository
from quant_vn.market.costs import TransactionCosts
from quant_vn.research.experiment import compare_strategies
from quant_vn.strategies.buy_and_hold import BuyAndHoldStrategy
from quant_vn.strategies.moving_average_cross import MovingAverageCrossStrategy, MACrossParams
from quant_vn.strategies.rsi_mean_reversion import RSIMeanReversionStrategy, RSIMeanReversionParams

SYMBOL = "FPT"
START = "2020-01-01"
END = "2024-12-31"
INITIAL_CAPITAL = 100_000_000  # 100M VND


def get_prices() -> pd.DataFrame:
    """Try DB first, fall back to synthetic data."""
    db = Database(url=settings.database_url)
    db.init_db()
    repo = PriceRepository(db)
    prices = repo.get_ohlcv(SYMBOL, START, END)
    if not prices.empty:
        print(f"Loaded {len(prices)} rows of {SYMBOL} from database.")
        return prices

    print(f"No real data for {SYMBOL}. Generating synthetic data for demonstration...")
    return _generate_synthetic_fpt()


def _generate_synthetic_fpt() -> pd.DataFrame:
    """Synthetic FPT-like price series (not real data)."""
    rng = np.random.default_rng(2024)
    n = 1200
    dates = pd.date_range(START, periods=n, freq="B")

    # Simulate a trending-up stock with volatility
    drift = 0.0006
    vol = 0.016
    returns = rng.normal(drift, vol, n)
    close = 50_000 * np.exp(np.cumsum(returns))  # Start at ~50,000 VND

    high = close * (1 + rng.uniform(0.002, 0.025, n))
    low = close * (1 - rng.uniform(0.002, 0.025, n))
    open_ = low + rng.uniform(0, 1, n) * (high - low)
    volume = rng.integers(500_000, 8_000_000, n).astype(int)

    return pd.DataFrame({
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
        "volume": volume,
    }, index=dates)


def main():
    print(f"\n{'='*60}")
    print(f"quant-vn Example: {SYMBOL} Backtest")
    print(f"Period: {START} → {END}")
    print(f"Initial Capital: {INITIAL_CAPITAL:,.0f} VND")
    print(f"{'='*60}\n")

    prices = get_prices()

    costs = TransactionCosts(
        commission_rate=0.001,
        sell_tax_rate=0.001,
        slippage_bps=10,
    )

    strategies = [
        BuyAndHoldStrategy(),
        MovingAverageCrossStrategy(MACrossParams(fast_window=20, slow_window=60)),
        MovingAverageCrossStrategy(MACrossParams(fast_window=10, slow_window=30)),
        RSIMeanReversionStrategy(RSIMeanReversionParams(rsi_window=14, oversold_threshold=30, exit_threshold=70)),
    ]

    print("Running strategy comparison...\n")
    comparison = compare_strategies(
        strategies=strategies,
        prices=prices,
        symbol=SYMBOL,
        start_date=START,
        end_date=END,
        initial_capital=INITIAL_CAPITAL,
        costs=costs,
    )

    print("\n" + "="*80)
    print("STRATEGY COMPARISON RESULTS")
    print("="*80)
    display_cols = [
        "strategy", "total_return_pct", "cagr_pct",
        "sharpe", "max_drawdown_pct", "win_rate_pct", "n_trades"
    ]
    print(comparison[display_cols].to_string(index=False))
    print("\n⚠️  Synthetic data only — results do not reflect real trading performance.")
    print("    Import real OHLCV data with: quant-vn ingest --provider csv --path data/raw/FPT.csv\n")

    # Save detailed report for best strategy by Sharpe
    best_strategy_name = comparison.iloc[0]["strategy"]
    print(f"\nBest strategy by Sharpe: {best_strategy_name}")

    engine = BacktestEngine(costs=costs, initial_capital=INITIAL_CAPITAL)
    best_strategy = strategies[0]  # top of comparison
    for s in strategies:
        if s.describe() == best_strategy_name:
            best_strategy = s
            break

    result = engine.run(best_strategy, prices, symbol=SYMBOL)
    print_report(result)

    output_dir = Path("reports")
    paths = save_csv_report(result, output_dir=output_dir)
    print(f"\nSaved reports:")
    for name, path in paths.items():
        print(f"  {name}: {path}")


if __name__ == "__main__":
    main()
