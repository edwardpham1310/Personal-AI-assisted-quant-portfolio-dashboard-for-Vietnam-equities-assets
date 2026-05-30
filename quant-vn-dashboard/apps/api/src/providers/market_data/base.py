"""Abstract market data provider interface."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date
from typing import Literal

from schemas.market import IndexInfo, OHLCVBar, ProviderStatus, Quote, Security

Interval = Literal["1m", "5m", "15m", "30m", "1h"]


class ProviderError(Exception):
    """Raised when a market data provider can't fulfill a request.

    ``status_code`` lets routes map a provider failure to a sensible HTTP code
    without exposing upstream details to the caller.
    """

    def __init__(self, message: str, *, status_code: int = 502) -> None:
        super().__init__(message)
        self.status_code = status_code


class MarketDataProvider(ABC):
    """Every concrete provider implements this surface."""

    name: str = "abstract"

    @abstractmethod
    async def get_access_token(self) -> str: ...

    @abstractmethod
    async def get_securities(self, exchange: str | None = None) -> list[Security]: ...

    @abstractmethod
    async def get_security_details(self, symbol: str) -> Security: ...

    @abstractmethod
    async def get_index_list(self) -> list[IndexInfo]: ...

    @abstractmethod
    async def get_index_components(self, index_code: str) -> list[str]: ...

    @abstractmethod
    async def get_daily_ohlcv(
        self, symbol: str, start_date: date, end_date: date
    ) -> list[OHLCVBar]: ...

    @abstractmethod
    async def get_intraday_ohlcv(
        self,
        symbol: str,
        start_date: date,
        end_date: date,
        interval: Interval,
    ) -> list[OHLCVBar]: ...

    @abstractmethod
    async def get_daily_stock_price(self, symbols: list[str]) -> list[Quote]: ...

    @abstractmethod
    async def get_daily_index(self, index_code: str) -> list[OHLCVBar]: ...

    @abstractmethod
    async def get_latest_quotes(self, symbols: list[str]) -> list[Quote]: ...

    @abstractmethod
    async def status(self) -> ProviderStatus: ...
