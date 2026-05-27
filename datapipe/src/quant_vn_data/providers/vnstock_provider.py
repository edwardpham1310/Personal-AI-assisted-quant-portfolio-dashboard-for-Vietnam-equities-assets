"""Vnstock provider — research/prototype/fallback data source.

Requires: pip install vnstock
Gracefully degrades if vnstock is not installed.
"""

from __future__ import annotations

import logging
from typing import Any

import pandas as pd

from .base import MarketDataProvider, ProviderError

logger = logging.getLogger(__name__)


class VnstockProvider(MarketDataProvider):
    name = "vnstock"

    def __init__(self) -> None:
        self._vnstock = _import_vnstock()

    def get_symbols(self, exchange: str | None = None) -> pd.DataFrame:
        if self._vnstock is None:
            raise ProviderError("vnstock is not installed. Run: pip install vnstock")
        try:
            stock = self._vnstock.Vnstock()
            df = stock.stock(symbol="VCB", source="VCI").listing.all_symbols()
            if exchange and "exchange" in df.columns:
                df = df[df["exchange"].str.upper() == exchange.upper()]
            return df
        except Exception as exc:
            raise ProviderError(f"vnstock get_symbols failed: {exc}") from exc

    def get_daily_ohlcv(self, symbol: str, start_date: str, end_date: str) -> pd.DataFrame:
        if self._vnstock is None:
            raise ProviderError("vnstock is not installed. Run: pip install vnstock")
        try:
            stock = self._vnstock.Vnstock().stock(symbol=symbol, source="VCI")
            df = stock.quote.history(start=start_date, end=end_date, interval="1D")
            if df is None or df.empty:
                return pd.DataFrame()
            df = df.copy()
            df["symbol"] = symbol
            return df
        except Exception as exc:
            raise ProviderError(f"vnstock get_daily_ohlcv({symbol}) failed: {exc}") from exc

    def get_security_details(self, symbol: str) -> dict[str, Any]:
        if self._vnstock is None:
            raise ProviderError("vnstock is not installed")
        try:
            stock = self._vnstock.Vnstock().stock(symbol=symbol, source="VCI")
            return stock.company.overview().to_dict(orient="records")[0]
        except Exception as exc:
            raise ProviderError(f"vnstock get_security_details({symbol}) failed: {exc}") from exc


def _import_vnstock() -> Any | None:
    try:
        import vnstock  # type: ignore[import]
        return vnstock
    except ImportError:
        logger.warning(
            "vnstock package not installed — VnstockProvider will raise ProviderError. "
            "Install with: pip install vnstock"
        )
        return None
