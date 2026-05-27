"""RSI Mean Reversion strategy."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from ..indicators.momentum import rsi
from .base import AbstractStrategy, StrategyParams


@dataclass
class RSIMeanReversionParams(StrategyParams):
    rsi_window: int = 14
    oversold_threshold: float = 30.0   # enter long when RSI < this
    exit_threshold: float = 70.0       # exit when RSI > this


class RSIMeanReversionStrategy(AbstractStrategy):
    """
    Mean reversion using RSI.

    Rules:
    - Enter long (1) when RSI drops below oversold_threshold
    - Hold long (1) while position is open
    - Exit (0) when RSI rises above exit_threshold

    The state machine ensures: we are either in a trade or flat.
    No lookahead: RSI at T uses only close prices up to T.
    """

    def __init__(self, params: RSIMeanReversionParams | None = None):
        super().__init__(params or RSIMeanReversionParams())

    @property
    def name(self) -> str:
        return "rsi_mean_reversion"

    def validate_params(self) -> None:
        p = self.params
        if not isinstance(p, RSIMeanReversionParams):
            raise TypeError("Expected RSIMeanReversionParams")
        if p.rsi_window < 2:
            raise ValueError("rsi_window must be >= 2")
        if not (0 < p.oversold_threshold < p.exit_threshold < 100):
            raise ValueError("Must have: 0 < oversold_threshold < exit_threshold < 100")

    def generate_signals(self, prices: pd.DataFrame) -> pd.Series:
        self.validate_params()
        p: RSIMeanReversionParams = self.params  # type: ignore[assignment]

        rsi_vals = rsi(prices["close"], window=p.rsi_window)

        # Build stateful signal: 1 while in trade, 0 while flat
        signals = pd.Series(0.0, index=prices.index)
        in_trade = False
        for i, (idx, rsi_val) in enumerate(rsi_vals.items()):
            if pd.isna(rsi_val):
                signals.iloc[i] = 0.0
                continue
            if not in_trade and rsi_val < p.oversold_threshold:
                in_trade = True
            elif in_trade and rsi_val > p.exit_threshold:
                in_trade = False
            signals.iloc[i] = 1.0 if in_trade else 0.0

        return signals
