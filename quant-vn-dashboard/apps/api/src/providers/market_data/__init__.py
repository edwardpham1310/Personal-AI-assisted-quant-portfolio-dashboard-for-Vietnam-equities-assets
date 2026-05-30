"""Market data providers.

The API consumes a ``MarketDataProvider`` abstract interface so production
(SSI FastConnect) and local development (mock) can be swapped via the
``SSI_USE_MOCK`` env var.
"""

from providers.market_data.base import (
    Interval,
    MarketDataProvider,
    ProviderError,
)
from providers.market_data.mock_provider import MockMarketDataProvider
from providers.market_data.ssi_fastconnect import SSIFastConnectProvider

__all__ = [
    "Interval",
    "MarketDataProvider",
    "ProviderError",
    "MockMarketDataProvider",
    "SSIFastConnectProvider",
]
