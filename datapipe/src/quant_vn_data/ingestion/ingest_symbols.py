"""Orchestrate symbol ingestion: provider → raw store → normalization → SQLite."""

from __future__ import annotations

import logging

from quant_vn_data.normalization import normalize_symbols
from quant_vn_data.providers.base import MarketDataProvider, ProviderError
from quant_vn_data.storage.sqlite_store import SQLiteStore

from .raw_store import RawStore

logger = logging.getLogger(__name__)


def ingest_symbols(
    provider: MarketDataProvider,
    store: SQLiteStore,
    exchange: str | None = None,
    raw_store: RawStore | None = None,
) -> int:
    logger.info("Ingesting symbols: provider=%s exchange=%s", provider.name, exchange or "ALL")

    try:
        raw_df = provider.get_symbols(exchange=exchange)
    except (ProviderError, NotImplementedError) as exc:
        logger.error("Provider error fetching symbols: %s", exc)
        return 0

    if raw_df.empty:
        logger.warning("No symbols returned from %s", provider.name)
        return 0

    if raw_store is not None:
        raw_store.store(
            provider=provider.name,
            dataset="symbols",
            symbol="__all__",
            data=raw_df.to_dict(orient="records"),
            request_params={"exchange": exchange},
        )

    normalized = normalize_symbols(raw_df, source=provider.name, default_exchange=exchange)
    if normalized.empty:
        return 0

    inserted = store.upsert_symbols(normalized)
    logger.info("Upserted %d symbols from %s", inserted, provider.name)
    return inserted
