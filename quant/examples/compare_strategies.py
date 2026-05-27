"""
Example: Compare all 4 strategies on a portfolio of Vietnamese blue chips.

Uses synthetic data as fallback when no real data is available.
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
from quant_vn.market.universe import BLUE_CHIPS
from quant_vn.strategies.breakout import BreakoutStrategy, BreakoutParams
from quant_vn.strategies.buy_and_hold import BuyAndHoldStrategy
from quant_vn.strategies.moving_average_cross import MovingAverageCrossStrategy, MACrossParams
from quant_vn.strategies.rsi_mean_reversion import RSIMeanReversionStrategy, RSIMeanReversionParams

SYMBOLS = ["FPT", "MWG", "HPG", "VNM", "SSI"]  # subset of blue chips for speed
START = "2021-01-01"
END = "2024-12-31"
INITIAL_CAPITAL = 100_000_000


def get_prices(symbol: str) -> pd.DataFrame:
    db = Database(url=settings.database_url)
    db.init_db()
    prices = PriceRepository(db).get_ohlcv(symbol, START, END)
    if not prices.empty:
        return prices
    return _synthetic(symbol)


def _synthetic(symbol: str) -> pd.DataFrame:
    rng = np.random.default_rng(hash(symbol) % 2**32)
    n = 900
    dates = pd.date_range(START, periods=n, freq="B")
    close = 100_000 * np.exp(np.cumsum(rng.normal(0.0004, 0.015, n)))
    high = close * (1 + rng.uniform(0.002, 0.02, n))
    low = close * (1 - rng.uniform(0.002, 0.02, n))
    return pd.DataFrame({
        "open": close,
        "high": high,
        "low": low,
        "close": close,
        "volume": rng.integers(500_000, 5_000_000, n).astype(int),
    }, index=dates)


def main():
    strategies = [
        ("BuyHold", BuyAndHoldStrategy()),
        ("MA_10_30", MovingAverageCrossStrategy(MACrossParams(10, 30))),
        ("MA_20_60", MovingAverageCrossStrategy(MACrossParams(20, 60))),
        ("RSI_14", RSIMeanReversionStrategy(RSIMeanReversionParams(14, 30, 70))),
        ("Breakout_20", BreakoutStrategy(BreakoutParams(20, volume_confirmation=False))),
    ]

    costs = TransactionCosts(commission_rate=0.001, sell_tax_rate=0.001, slippage_bps=10)
    engine = BacktestEngine(costs=costs, initial_capital=INITIAL_CAPITAL)

    rows = []
    for symbol in SYMBOLS:
        prices = get_prices(symbol)
        for strat_name, strategy in strategies:
            try:
                result = engine.run(strategy, prices, symbol=symbol)
                m = result.metrics
                rows.append({
                    "symbol": symbol,
                    "strategy": strat_name,
                    "cagr_pct": round(m.get("cagr_pct", 0), 2),
                    "sharpe": round(m.get("sharpe", 0), 3),
                    "max_dd_pct": round(m.get("max_drawdown_pct", 0), 2),
                    "win_rate_pct": round(m.get("win_rate_pct", 0), 1),
                    "n_trades": int(m.get("n_trades", 0)),
                })
            except Exception as e:
                print(f"  Failed {symbol}/{strat_name}: {e}")

    df = pd.DataFrame(rows)
    print("\n" + "="*90)
    print("MULTI-SYMBOL STRATEGY COMPARISON (Synthetic Data)")
    print("="*90)
    print(df.pivot_table(
        index="symbol",
        columns="strategy",
        values="sharpe",
        aggfunc="mean",
    ).round(3).to_string())

    print("\nFull results:")
    print(df.sort_values(["symbol", "sharpe"], ascending=[True, False]).to_string(index=False))
    print("\n⚠️  Synthetic data only. Real results will differ significantly.")


if __name__ == "__main__":
    main()
