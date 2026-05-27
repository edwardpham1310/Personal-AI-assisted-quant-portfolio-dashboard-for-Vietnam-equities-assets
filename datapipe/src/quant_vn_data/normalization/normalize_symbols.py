"""Normalize raw symbol lists from providers into the canonical schema."""

from __future__ import annotations

import logging
from typing import Any

import pandas as pd

from .schemas import SymbolRow

logger = logging.getLogger(__name__)


def normalize_symbols(
    df: pd.DataFrame,
    source: str,
    default_exchange: str | None = None,
) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame()

    df = df.copy()

    col_map: dict[str, str] = {
        "ticker": "symbol", "stockSymbol": "symbol", "code": "symbol",
        "stockName": "name", "organName": "name", "comGroupCode": "exchange",
        "stockType": "type", "listedDate": "listed_date", "delistedDate": "delisted_date",
        "status": "status", "isin": "isin",
    }
    df.rename(columns={k: v for k, v in col_map.items() if k in df.columns}, inplace=True)

    if "exchange" not in df.columns and default_exchange:
        df["exchange"] = default_exchange
    if "source" not in df.columns:
        df["source"] = source

    rows: list[dict[str, Any]] = []
    for _, row in df.iterrows():
        try:
            validated = SymbolRow(**row.to_dict())
            rows.append(validated.model_dump())
        except Exception as exc:
            logger.debug("normalize_symbols: skipping row — %s", exc)

    return pd.DataFrame(rows) if rows else pd.DataFrame()
