"""Orchestrate OHLCV ingestion: provider → raw store → normalization → SQLite."""

from __future__ import annotations

import logging
from datetime import date

import pandas as pd

from quant_vn_data.normalization import normalize_ohlcv
from quant_vn_data.providers.base import MarketDataProvider, ProviderError
from quant_vn_data.storage.sqlite_store import SQLiteStore

from .raw_store import RawStore

logger = logging.getLogger(__name__)


def ingest_ohlcv(
    provider: MarketDataProvider,
    symbol: str,
    start_date: str,
    end_date: str,
    store: SQLiteStore,
    raw_store: RawStore | None = None,
    exchange: str | None = None,
) -> int:
    """Fetch, store raw, normalize, and upsert OHLCV for a single symbol.

    Returns the number of rows inserted.
    """
    logger.info("Ingesting OHLCV: provider=%s symbol=%s %s→%s", provider.name, symbol, start_date, end_date)

    try:
        raw_df = provider.get_daily_ohlcv(symbol, start_date, end_date)
    except ProviderError as exc:
        logger.error("Provider error for %s: %s", symbol, exc)
        return 0
    except Exception as exc:
        logger.error("Unexpected error fetching %s: %s", symbol, exc)
        return 0

    if raw_df.empty:
        logger.warning("No data returned for %s", symbol)
        return 0

    if raw_store is not None:
        raw_store.store(
            provider=provider.name,
            dataset="daily_ohlcv",
            symbol=symbol,
            data=raw_df.to_dict(orient="records"),
            request_params={"start_date": start_date, "end_date": end_date},
        )

    normalized = normalize_ohlcv(raw_df, source=provider.name, symbol=symbol, exchange=exchange)
    if normalized.empty:
        logger.warning("Normalization produced no rows for %s", symbol)
        return 0

    inserted = store.upsert_ohlcv(normalized)
    logger.info("Inserted %d OHLCV rows for %s from %s", inserted, symbol, provider.name)
    return inserted
