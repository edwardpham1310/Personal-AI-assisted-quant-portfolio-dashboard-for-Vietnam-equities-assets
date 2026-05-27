"""CSV local file provider — for development, testing, and offline use."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import pandas as pd

from .base import MarketDataProvider, ProviderError

logger = logging.getLogger(__name__)

_DATE_ALIASES = ["trading_date", "date", "Date", "tradingDate", "time"]
_SYMBOL_ALIASES = ["symbol", "ticker", "Ticker", "Symbol"]
_OPEN_ALIASES = ["open", "Open"]
_HIGH_ALIASES = ["high", "High"]
_LOW_ALIASES = ["low", "Low"]
_CLOSE_ALIASES = ["close", "Close"]
_VOLUME_ALIASES = ["volume", "Volume"]


def _pick_column(df: pd.DataFrame, candidates: list[str]) -> str | None:
    for c in candidates:
        if c in df.columns:
            return c
    return None


class CSVProvider(MarketDataProvider):
    name = "csv"

    def __init__(self, path: str | Path, symbol: str | None = None, exchange: str | None = None) -> None:
        self.path = Path(path)
        self._default_symbol = symbol
        self._default_exchange = exchange
        self._df: pd.DataFrame | None = None

    def _load(self) -> pd.DataFrame:
        if self._df is not None:
            return self._df
        if not self.path.exists():
            raise ProviderError(f"CSV file not found: {self.path}")
        try:
            df = pd.read_csv(self.path, parse_dates=False)
        except Exception as exc:
            raise ProviderError(f"Failed to read CSV {self.path}: {exc}") from exc
        self._df = df
        return df

    def get_symbols(self, exchange: str | None = None) -> pd.DataFrame:
        df = self._load()
        col = _pick_column(df, _SYMBOL_ALIASES)
        if col is None:
            return pd.DataFrame(columns=["symbol", "exchange", "source"])
        symbols = df[col].dropna().unique().tolist()
        rows = [{"symbol": s, "exchange": self._default_exchange or "", "source": "csv"} for s in symbols]
        result = pd.DataFrame(rows)
        if exchange:
            result = result[result["exchange"] == exchange]
        return result

    def get_daily_ohlcv(self, symbol: str, start_date: str, end_date: str) -> pd.DataFrame:
        df = self._load()

        # Identify date column
        date_col = _pick_column(df, _DATE_ALIASES)
        if date_col is None:
            raise ProviderError("CSV has no recognizable date column")

        df = df.copy()
        df["trading_date"] = pd.to_datetime(df[date_col], errors="coerce").dt.date
        df = df.dropna(subset=["trading_date"])

        start = pd.Timestamp(start_date).date()
        end = pd.Timestamp(end_date).date()
        df = df[(df["trading_date"] >= start) & (df["trading_date"] <= end)]

        # Filter by symbol if the CSV has a symbol column
        sym_col = _pick_column(df, _SYMBOL_ALIASES)
        if sym_col is not None:
            df = df[df[sym_col].astype(str).str.upper() == symbol.upper()]
        if "symbol" not in df.columns:
            df["symbol"] = symbol

        # Rename OHLCV columns
        rename: dict[str, str] = {}
        for aliases, canonical in [
            (_OPEN_ALIASES, "open"), (_HIGH_ALIASES, "high"),
            (_LOW_ALIASES, "low"), (_CLOSE_ALIASES, "close"),
            (_VOLUME_ALIASES, "volume"),
        ]:
            col = _pick_column(df, aliases)
            if col and col != canonical:
                rename[col] = canonical
        df.rename(columns=rename, inplace=True)

        return df.reset_index(drop=True)

    def get_security_details(self, symbol: str) -> dict[str, Any]:
        return {"symbol": symbol, "source": "csv"}
