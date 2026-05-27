"""Orchestrate corporate action ingestion."""

from __future__ import annotations

import logging

from quant_vn_data.normalization import normalize_corporate_actions
from quant_vn_data.providers.base import CorporateActionProvider, ProviderError
from quant_vn_data.storage.sqlite_store import SQLiteStore

from .raw_store import RawStore

logger = logging.getLogger(__name__)


def ingest_corporate_actions(
    provider: CorporateActionProvider,
    store: SQLiteStore,
    symbol: str | None = None,
    start_date: str = "2010-01-01",
    end_date: str = "2099-12-31",
    raw_store: RawStore | None = None,
) -> int:
    logger.info(
        "Ingesting corporate actions: provider=%s symbol=%s",
        provider.name, symbol or "ALL",
    )

    try:
        raw_df = provider.get_corporate_actions(symbol=symbol, start_date=start_date, end_date=end_date)
    except (ProviderError, NotImplementedError) as exc:
        logger.error("Provider error fetching corporate actions: %s", exc)
        return 0

    if raw_df.empty:
        logger.warning("No corporate actions returned")
        return 0

    if raw_store is not None:
        raw_store.store(
            provider=provider.name,
            dataset="corporate_actions",
            symbol=symbol or "__all__",
            data=raw_df.to_dict(orient="records"),
            request_params={"symbol": symbol, "start_date": start_date, "end_date": end_date},
        )

    normalized = normalize_corporate_actions(raw_df, source=provider.name)
    if normalized.empty:
        return 0

    inserted = store.insert_corporate_actions(normalized)
    logger.info("Inserted %d corporate action rows from %s", inserted, provider.name)
    return inserted
