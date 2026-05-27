"""Moving Average Crossover strategy."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from ..indicators.trend import ma_position_signal
from .base import AbstractStrategy, StrategyParams


@dataclass
class MACrossParams(StrategyParams):
    fast_window: int = 20
    slow_window: int = 50
    method: str = "sma"  # sma | ema


class MovingAverageCrossStrategy(AbstractStrategy):
    """
    Long when fast MA > slow MA, flat otherwise.

    Rules:
    - Buy (1) when fast SMA/EMA > slow SMA/EMA
    - Flat (0) when fast SMA/EMA <= slow SMA/EMA
    - Uses CLOSE price for MA calculation

    No lookahead: all MAs are computed causally (only data up to bar T used).
    """

    def __init__(self, params: MACrossParams | None = None):
        super().__init__(params or MACrossParams())

    @property
    def name(self) -> str:
        return "ma_cross"

    def validate_params(self) -> None:
        p = self.params
        if not isinstance(p, MACrossParams):
            raise TypeError("Expected MACrossParams")
        if p.fast_window < 2:
            raise ValueError("fast_window must be >= 2")
        if p.slow_window <= p.fast_window:
            raise ValueError("slow_window must be > fast_window")
        if p.method not in ("sma", "ema"):
            raise ValueError("method must be 'sma' or 'ema'")

    def generate_signals(self, prices: pd.DataFrame) -> pd.Series:
        self.validate_params()
        p: MACrossParams = self.params  # type: ignore[assignment]
        signal = ma_position_signal(
            prices["close"],
            fast_window=p.fast_window,
            slow_window=p.slow_window,
            method=p.method,
        )
        # Fill NaN (warmup period) with 0 = flat
        return signal.fillna(0.0)
