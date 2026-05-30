"""Abstract data provider interface."""

from __future__ import annotations

from abc import ABC, abstractmethod

import pandas as pd


REQUIRED_COLUMNS = {"date", "open", "high", "low", "close", "volume"}


class AbstractDataProvider(ABC):
    """
    All data providers must implement this interface.
    Providers return raw DataFrames; cleaning/validation is a separate step.
    """

    @abstractmethod
    def get_ohlcv(
        self,
        symbol: str,
        start_date: str,
        end_date: str,
        timeframe: str = "1d",
    ) -> pd.DataFrame:
        """
        Fetch OHLCV data for a symbol.

        Returns a DataFrame with at minimum these columns (case-insensitive):
            date, open, high, low, close, volume

        date column must be parseable as datetime.
        Prices are in native units (VND for Vietnam stocks).
        """
        ...

    @abstractmethod
    def get_symbols(self, exchange: str | None = None) -> list[str]:
        """Return list of available ticker symbols, optionally filtered by exchange."""
        ...

    def update_ohlcv(
        self,
        symbols: list[str],
        start_date: str,
        end_date: str,
    ) -> dict[str, pd.DataFrame]:
        """Fetch OHLCV for multiple symbols. Default implementation calls get_ohlcv in a loop."""
        results: dict[str, pd.DataFrame] = {}
        for sym in symbols:
            try:
                results[sym] = self.get_ohlcv(sym, start_date, end_date)
            except Exception as exc:
                print(f"[WARN] Failed to fetch {sym}: {exc}")
        return results

    @property
    def name(self) -> str:
        return self.__class__.__name__
