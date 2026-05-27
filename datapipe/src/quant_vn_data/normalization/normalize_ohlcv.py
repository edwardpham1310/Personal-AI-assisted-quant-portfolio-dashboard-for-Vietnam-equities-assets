"""Normalize raw provider OHLCV DataFrames into the canonical schema."""

from __future__ import annotations

import logging
from typing import Any

import pandas as pd

from .schemas import OHLCVRow

logger = logging.getLogger(__name__)

_COLUMN_ALIASES: dict[str, str] = {
    # date
    "trading_date": "trading_date",
    "date": "trading_date",
    "Date": "trading_date",
    "tradingDate": "trading_date",
    "TradingDate": "trading_date",
    "time": "trading_date",
    # symbol
    "ticker": "symbol",
    "Ticker": "symbol",
    "stockSymbol": "symbol",
    "Symbol": "symbol",
    # open
    "Open": "open",
    "priceOpen": "open",
    "OpenPrice": "open",
    "open": "open",
    # high
    "High": "high",
    "priceHigh": "high",
    "HighPrice": "high",
    "high": "high",
    # low
    "Low": "low",
    "priceLow": "low",
    "LowPrice": "low",
    "low": "low",
    # close
    "Close": "close",
    "priceClose": "close",
    "ClosePrice": "close",
    "close": "close",
    # adjusted close
    "Adj Close": "adjusted_close",
    "adj_close": "adjusted_close",
    "adjustedClose": "adjusted_close",
    # volume
    "Volume": "volume",
    "totalVolume": "volume",
    "TotalVolume": "volume",
    "matchingVolume": "volume",
    "volume": "volume",
    # value
    "totalValue": "value",
    "TotalValue": "value",
    "matchingValue": "value",
    "value": "value",
    # Vietnam-specific
    "referencePrice": "reference_price",
    "ceilingPrice": "ceiling_price",
    "floorPrice": "floor_price",
    "foreignBuyVolume": "foreign_buy_volume",
    "ForeignBuyVolume": "foreign_buy_volume",
    "foreignSellVolume": "foreign_sell_volume",
    "ForeignSellVolume": "foreign_sell_volume",
    "foreignBuyValue": "foreign_buy_value",
    "ForeignBuyValue": "foreign_buy_value",
    "foreignSellValue": "foreign_sell_value",
    "ForeignSellValue": "foreign_sell_value",
    "proprietaryBuyValue": "proprietary_buy_value",
    "proprietarySellValue": "proprietary_sell_value",
}


def normalize_ohlcv(
    df: pd.DataFrame,
    source: str,
    symbol: str | None = None,
    exchange: str | None = None,
    source_priority: int | None = None,
) -> pd.DataFrame:
    """Normalize a provider DataFrame into the canonical OHLCV schema.

    Returns a DataFrame ready for SQLiteStore.upsert_ohlcv().
    Invalid rows are logged and excluded (not silently dropped).
    """
    if df.empty:
        return pd.DataFrame()

    df = df.copy()
    df.rename(columns={k: v for k, v in _COLUMN_ALIASES.items() if k in df.columns}, inplace=True)

    if "symbol" not in df.columns and symbol:
        df["symbol"] = symbol
    if "exchange" not in df.columns and exchange:
        df["exchange"] = exchange

    df["source"] = source
    if source_priority is not None:
        df["source_priority"] = source_priority

    required = {"symbol", "trading_date"}
    missing = required - set(df.columns)
    if missing:
        logger.warning("normalize_ohlcv: missing required columns %s — skipping", missing)
        return pd.DataFrame()

    rows: list[dict[str, Any]] = []
    for _, row in df.iterrows():
        try:
            validated = OHLCVRow(**row.to_dict())
            rows.append(validated.model_dump())
        except Exception as exc:
            logger.warning("normalize_ohlcv: skipping row — %s", exc)

    if not rows:
        return pd.DataFrame()

    result = pd.DataFrame(rows)
    result = result.drop_duplicates(subset=["symbol", "trading_date", "source"])
    result = result.sort_values(["symbol", "trading_date"]).reset_index(drop=True)
    return result
