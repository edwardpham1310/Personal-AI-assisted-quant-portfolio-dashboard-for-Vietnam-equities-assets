"""Abstract strategy base class."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass

import pandas as pd


@dataclass
class StrategyParams:
    """Base class for strategy parameters. Subclasses add typed fields."""

    def to_dict(self) -> dict:
        return asdict(self)

    def describe(self) -> str:
        parts = [f"{k}={v}" for k, v in self.to_dict().items()]
        return ", ".join(parts)


class AbstractStrategy(ABC):
    """
    All strategies must implement this interface.

    Signal semantics:
      1  = long (buy / enter long position)
      0  = flat (no position)
     -1  = short (sell / exit long for long-only strategies)

    CRITICAL: generate_signals() must ONLY use information available at bar T
    to produce the signal at T. The backtest engine shifts signals by 1 bar
    before applying them (executes at T+1 open).

    Therefore: signal at row T may access data for rows 0..T inclusive.
    Never use .shift(-n) on any price/volume/indicator data inside this method.
    """

    def __init__(self, params: StrategyParams):
        self.params = params

    @property
    @abstractmethod
    def name(self) -> str:
        """Short machine-readable strategy identifier."""
        ...

    @abstractmethod
    def generate_signals(self, prices: pd.DataFrame) -> pd.Series:
        """
        Generate trading signals from price data.

        Args:
            prices: DataFrame with DatetimeIndex and columns
                    [open, high, low, close, volume].

        Returns:
            pd.Series with values in {-1, 0, 1}, same index as prices.
            NaN values are treated as 0 (hold) by the engine.
        """
        ...

    def validate_params(self) -> None:
        """Override to add parameter validation. Raise ValueError on invalid params."""
        pass

    def describe(self) -> str:
        return f"{self.name}({self.params.describe()})"

    def __repr__(self) -> str:
        return f"<Strategy: {self.describe()}>"
