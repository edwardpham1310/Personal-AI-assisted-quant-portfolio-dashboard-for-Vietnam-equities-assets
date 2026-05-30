"""Placeholder for future custom / paid API providers."""

from __future__ import annotations

import pandas as pd

from .base import AbstractDataProvider


class CustomProvider(AbstractDataProvider):
    """
    Extend this class to integrate with a paid data API (e.g. FireAnt, VNDirect, SSI).

    Steps:
    1. Subclass CustomProvider
    2. Implement get_ohlcv() and get_symbols()
    3. Store API credentials in .env (never in code)
    4. Register your provider in the CLI with --provider custom
    """

    def get_ohlcv(
        self,
        symbol: str,
        start_date: str,
        end_date: str,
        timeframe: str = "1d",
    ) -> pd.DataFrame:
        raise NotImplementedError(
            "CustomProvider is a placeholder. "
            "Subclass it and implement get_ohlcv() for your API."
        )

    def get_symbols(self, exchange: str | None = None) -> list[str]:
        raise NotImplementedError(
            "CustomProvider is a placeholder. "
            "Subclass it and implement get_symbols() for your API."
        )
