"""Buy-and-hold strategy: enter at first bar, hold until end."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from .base import AbstractStrategy, StrategyParams


@dataclass
class BuyAndHoldParams(StrategyParams):
    pass  # No parameters needed


class BuyAndHoldStrategy(AbstractStrategy):
    """
    Buy on the first available bar and hold until the end.

    Signal: 1 for every bar from the first available date onward.
    The engine will shift this by 1 bar → buys at the second bar's open.
    """

    def __init__(self):
        super().__init__(BuyAndHoldParams())

    @property
    def name(self) -> str:
        return "buy_and_hold"

    def generate_signals(self, prices: pd.DataFrame) -> pd.Series:
        signal = pd.Series(1.0, index=prices.index)
        signal.iloc[0] = 0.0  # no signal on first bar (no prior close to shift from)
        return signal
