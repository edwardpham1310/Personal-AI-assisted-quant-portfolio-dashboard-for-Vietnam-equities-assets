"""Breakout strategy: buy when price breaks above rolling high."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from ..indicators.volume import volume_ratio
from .base import AbstractStrategy, StrategyParams


@dataclass
class BreakoutParams(StrategyParams):
    lookback_window: int = 20          # rolling high lookback period
    volume_confirmation: bool = True   # require volume > avg to confirm breakout
    volume_window: int = 20            # window for average volume
    volume_multiplier: float = 1.5     # required volume ratio for confirmation
    trailing_stop_pct: float = 0.05    # 5% trailing stop from position high


class BreakoutStrategy(AbstractStrategy):
    """
    Breakout strategy.

    Rules:
    - Enter long (1) when close breaks above highest close of last lookback_window bars
    - Optionally confirm with volume > volume_multiplier * average_volume
    - Exit (0) when price falls more than trailing_stop_pct from highest close since entry
      OR when price falls back below the breakout level

    No lookahead: rolling high at T uses bars [T-window+1 .. T-1] (excludes T).
    This is critical: we use .shift(1) on the rolling high so signal at T
    compares today's close to yesterday's window-high.
    """

    def __init__(self, params: BreakoutParams | None = None):
        super().__init__(params or BreakoutParams())

    @property
    def name(self) -> str:
        return "breakout"

    def validate_params(self) -> None:
        p = self.params
        if not isinstance(p, BreakoutParams):
            raise TypeError("Expected BreakoutParams")
        if p.lookback_window < 2:
            raise ValueError("lookback_window must be >= 2")
        if p.trailing_stop_pct <= 0 or p.trailing_stop_pct >= 1:
            raise ValueError("trailing_stop_pct must be in (0, 1)")

    def generate_signals(self, prices: pd.DataFrame) -> pd.Series:
        self.validate_params()
        p: BreakoutParams = self.params  # type: ignore[assignment]

        close = prices["close"]

        # Rolling high of the past `lookback_window` bars — shift(1) prevents lookahead
        rolling_high = close.rolling(window=p.lookback_window, min_periods=p.lookback_window).max()
        rolling_high_prev = rolling_high.shift(1)

        # Volume confirmation
        if p.volume_confirmation and "volume" in prices.columns:
            vol_rat = volume_ratio(prices["volume"], window=p.volume_window)
            volume_ok = vol_rat >= p.volume_multiplier
        else:
            volume_ok = pd.Series(True, index=prices.index)

        # Breakout signal: close > yesterday's rolling high AND volume ok
        breakout = (close > rolling_high_prev) & volume_ok

        # Stateful signal with trailing stop
        signals = pd.Series(0.0, index=prices.index)
        in_trade = False
        entry_price = 0.0
        highest_since_entry = 0.0

        for i in range(len(prices)):
            idx = prices.index[i]
            c = close.iloc[i]

            if pd.isna(rolling_high_prev.iloc[i]):
                signals.iloc[i] = 0.0
                continue

            if not in_trade:
                if breakout.iloc[i]:
                    in_trade = True
                    entry_price = c
                    highest_since_entry = c
                signals.iloc[i] = 1.0 if in_trade else 0.0
            else:
                highest_since_entry = max(highest_since_entry, c)
                stop_level = highest_since_entry * (1 - p.trailing_stop_pct)
                # Exit on trailing stop or breakdown below rolling high
                if c < stop_level or c < rolling_high_prev.iloc[i]:
                    in_trade = False
                    signals.iloc[i] = 0.0
                else:
                    signals.iloc[i] = 1.0

        return signals
