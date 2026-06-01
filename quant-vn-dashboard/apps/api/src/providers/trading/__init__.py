"""Phase 2.5 SSI Trading providers — read-only views + order preview.

This package exposes a ``TradingProvider`` ABC that intentionally does
*not* define ``place_order`` / ``submit_order`` / ``cancel_order`` —
the safety of the system is enforced by the type system: there is no
overridable method that could ever reach SSI's NewOrder endpoint.

The forbidden routes are wired explicitly in ``api/routes/trading.py``
to return HTTP 501 and emit an audit event.
"""

from providers.trading.base import (
    TradingProvider,
    TradingProviderError,
)
from providers.trading.mock_trading import MockTradingProvider
from providers.trading.ssi_trading import SSITradingProvider

__all__ = [
    "TradingProvider",
    "TradingProviderError",
    "MockTradingProvider",
    "SSITradingProvider",
]
