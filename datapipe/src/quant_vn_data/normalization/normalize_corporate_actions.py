"""Normalize corporate action records from providers."""

from __future__ import annotations

import logging
from typing import Any

import pandas as pd

from .schemas import CorporateActionRow

logger = logging.getLogger(__name__)

ACTION_TYPE_MAP: dict[str, str] = {
    "cash_dividend": "CASH_DIVIDEND",
    "cashdividend": "CASH_DIVIDEND",
    "dividend": "CASH_DIVIDEND",
    "stock_dividend": "STOCK_DIVIDEND",
    "stockdividend": "STOCK_DIVIDEND",
    "bonus": "BONUS_SHARES",
    "bonus_shares": "BONUS_SHARES",
    "rights_issue": "RIGHTS_ISSUE",
    "rightsissue": "RIGHTS_ISSUE",
    "split": "SPLIT",
    "stock_split": "SPLIT",
    "consolidation": "CONSOLIDATION",
    "reverse_split": "CONSOLIDATION",
    "ticker_change": "TICKER_CHANGE",
}


def normalize_corporate_actions(df: pd.DataFrame, source: str) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame()

    df = df.copy()

    col_map: dict[str, str] = {
        "ticker": "symbol", "stockSymbol": "symbol", "code": "symbol",
        "isin": "isin",
        "exchange": "exchange",
        "announcementDate": "announcement_date",
        "recordDate": "record_date",
        "exDate": "ex_date",
        "paymentDate": "payment_date",
        "actionType": "action_type",
        "eventType": "action_type",
        "cashDividend": "cash_dividend",
        "dividendAmount": "cash_dividend",
        "stockDividendRatio": "stock_dividend_ratio",
        "bonusShareRatio": "bonus_share_ratio",
        "rightsIssueRatio": "rights_issue_ratio",
        "rightsIssuePrice": "rights_issue_price",
        "splitRatio": "split_ratio",
        "rawText": "raw_text",
        "sourceUrl": "source_url",
    }
    df.rename(columns={k: v for k, v in col_map.items() if k in df.columns}, inplace=True)

    if "action_type" in df.columns:
        df["action_type"] = df["action_type"].str.lower().str.strip().map(
            lambda x: ACTION_TYPE_MAP.get(x, x.upper() if isinstance(x, str) else "UNKNOWN")
        )

    df["source"] = source

    rows: list[dict[str, Any]] = []
    for _, row in df.iterrows():
        try:
            validated = CorporateActionRow(**row.to_dict())
            rows.append(validated.model_dump())
        except Exception as exc:
            logger.debug("normalize_corporate_actions: skipping row — %s", exc)

    return pd.DataFrame(rows) if rows else pd.DataFrame()
