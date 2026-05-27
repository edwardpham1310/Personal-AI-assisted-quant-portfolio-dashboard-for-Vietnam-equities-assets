"""
Example: Run MA crossover across VN30 universe (synthetic data).

Demonstrates multi-symbol portfolio backtesting.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import numpy as np
import pandas as pd

from quant_vn.backtest.engine import BacktestEngine
from quant_vn.config.settings import settings
from quant_vn.data.storage import Database, PriceRepository
from quant_vn.market.costs import TransactionCosts
from quant_vn.market.universe import VN30_SYMBOLS
from quant_vn.strategies.moving_average_cross import MovingAverageCrossStrategy, MACrossParams

START = "2021-01-01"
END = "2024-12-31"
INITIAL_CAPITAL = 100_000_000


def main():
    strategy = MovingAverageCrossStrategy(MACrossParams(fast_window=20, slow_window=60))
    costs = TransactionCosts(0.001, 0.001, 10)
    engine = BacktestEngine(costs=costs, initial_capital=INITIAL_CAPITAL)

    db = Database(url=settings.database_url)
    db.init_db()
    repo = PriceRepository(db)

    results = []
    for symbol in VN30_SYMBOLS[:10]:  # First 10 to keep demo fast
        prices = repo.get_ohlcv(symbol, START, END)
        if prices.empty:
            # Synthetic fallback
            rng = np.random.default_rng(hash(symbol) % 2**32)
            n = 800
            dates = pd.date_range(START, periods=n, freq="B")
            close = 50_000 * np.exp(np.cumsum(rng.normal(0.0003, 0.014, n)))
            prices = pd.DataFrame({
                "open": close,
                "high": close * (1 + rng.uniform(0.002, 0.02, n)),
                "low": close * (1 - rng.uniform(0.002, 0.02, n)),
                "close": close,
                "volume": rng.integers(500_000, 5_000_000, n).astype(int),
            }, index=dates)

        result = engine.run(strategy, prices, symbol=symbol)
        results.append({
            "symbol": symbol,
            "cagr_pct": result.metrics.get("cagr_pct", 0),
            "sharpe": result.metrics.get("sharpe", 0),
            "max_dd_pct": result.metrics.get("max_drawdown_pct", 0),
            "n_trades": result.metrics.get("n_trades", 0),
            "win_rate_pct": result.metrics.get("win_rate_pct", 0),
        })

    df = pd.DataFrame(results).sort_values("sharpe", ascending=False)
    print("\nVN30 Universe — MA Crossover (20/60) Backtest (Synthetic Data)")
    print("="*70)
    print(df.to_string(index=False))
    print("\n⚠️  Synthetic data only.")


if __name__ == "__main__":
    main()
