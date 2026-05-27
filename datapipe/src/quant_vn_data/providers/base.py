"""Abstract base classes for all data providers."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

import pandas as pd


class ProviderError(Exception):
    """Raised when a provider fails to fetch or parse data."""


class MarketDataProvider(ABC):
    """Interface every market-data provider must implement."""

    name: str = "base"

    @abstractmethod
    def get_symbols(self, exchange: str | None = None) -> pd.DataFrame:
        """Return a DataFrame of available symbols.

        Columns: symbol, exchange, name, type, status (at minimum).
        """

    @abstractmethod
    def get_daily_ohlcv(
        self,
        symbol: str,
        start_date: str,
        end_date: str,
    ) -> pd.DataFrame:
        """Return daily OHLCV data for a symbol.

        Columns: date, symbol, open, high, low, close, volume.
        Additional provider-specific columns are allowed.
        """

    def get_intraday_ohlcv(
        self,
        symbol: str,
        start_date: str,
        end_date: str,
        interval: str = "1m",
    ) -> pd.DataFrame:
        """Return intraday OHLCV. Providers that don't support this raise NotImplementedError."""
        raise NotImplementedError(f"{self.name} does not support intraday OHLCV")

    def get_index_list(self) -> pd.DataFrame:
        """Return a DataFrame of available indexes."""
        raise NotImplementedError(f"{self.name} does not support index listing")

    def get_index_components(self, index_code: str) -> pd.DataFrame:
        """Return constituent symbols for an index."""
        raise NotImplementedError(f"{self.name} does not support index components")

    def get_security_details(self, symbol: str) -> dict[str, Any]:
        """Return metadata for a single security."""
        raise NotImplementedError(f"{self.name} does not support security details")


class CorporateActionProvider(ABC):
    """Interface every corporate-action provider must implement."""

    name: str = "base_ca"

    @abstractmethod
    def get_corporate_actions(
        self,
        symbol: str | None,
        start_date: str,
        end_date: str,
    ) -> pd.DataFrame:
        """Return corporate actions in normalized form.

        Columns: symbol, announcement_date, record_date, ex_date, payment_date,
                 action_type, cash_dividend, stock_dividend_ratio, ...
        """
