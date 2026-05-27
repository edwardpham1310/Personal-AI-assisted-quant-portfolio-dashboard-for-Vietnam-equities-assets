"""High-level SQLite read/write operations for all normalized tables."""

from __future__ import annotations

import logging
from datetime import date
from typing import Any

import pandas as pd
from sqlalchemy import delete, func, select, text, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from .database import Database
from .migrations import (
    CorporateActionRecord,
    DataQualityIssueRecord,
    LiquidityFeatureRecord,
    OHLCVDailyRecord,
    ProviderReconciliationRecord,
    SymbolRecord,
)

logger = logging.getLogger(__name__)

_ALLOWED_TABLES = frozenset([
    "symbols", "ohlcv_daily", "corporate_actions",
    "provider_reconciliation", "data_quality_issues", "liquidity_features",
])


class SQLiteStore:
    def __init__(self, db: Database) -> None:
        self.db = db

    # ── OHLCV ──────────────────────────────────────────────────────────────

    def upsert_ohlcv(self, df: pd.DataFrame) -> int:
        """Bulk-insert normalized OHLCV rows; skip on duplicate (symbol, date, source)."""
        if df.empty:
            return 0
        records = [_coerce_ohlcv(r) for r in df.to_dict(orient="records")]
        with self.db.session() as session:
            before = session.scalar(select(func.count()).select_from(OHLCVDailyRecord))
            # Single executemany — orders of magnitude faster than row-by-row
            stmt = sqlite_insert(OHLCVDailyRecord).on_conflict_do_nothing(
                index_elements=["symbol", "trading_date", "source"]
            )
            session.execute(stmt, records)
            session.commit()
            after = session.scalar(select(func.count()).select_from(OHLCVDailyRecord))
        return (after or 0) - (before or 0)

    def query_ohlcv(
        self,
        symbol: str,
        start_date: str | date | None = None,
        end_date: str | date | None = None,
        source: str | None = None,
    ) -> pd.DataFrame:
        with self.db.session() as session:
            stmt = select(OHLCVDailyRecord).where(OHLCVDailyRecord.symbol == symbol)
            if start_date:
                stmt = stmt.where(OHLCVDailyRecord.trading_date >= start_date)
            if end_date:
                stmt = stmt.where(OHLCVDailyRecord.trading_date <= end_date)
            if source:
                stmt = stmt.where(OHLCVDailyRecord.source == source)
            stmt = stmt.order_by(OHLCVDailyRecord.trading_date)
            rows = session.scalars(stmt).all()
        return _records_to_df(rows) if rows else pd.DataFrame()

    def delete_ohlcv(self, symbol: str, source: str) -> int:
        with self.db.session() as session:
            result = session.execute(
                delete(OHLCVDailyRecord).where(
                    OHLCVDailyRecord.symbol == symbol,
                    OHLCVDailyRecord.source == source,
                )
            )
            session.commit()
        return result.rowcount

    def update_ohlcv_quality_status(
        self,
        symbol: str,
        trading_date: date,
        source: str,
        quality_status: str,
    ) -> None:
        """Write quality_status back to ohlcv_daily after validation."""
        with self.db.session() as session:
            session.execute(
                update(OHLCVDailyRecord)
                .where(
                    OHLCVDailyRecord.symbol == symbol,
                    OHLCVDailyRecord.trading_date == trading_date,
                    OHLCVDailyRecord.source == source,
                )
                .values(quality_status=quality_status)
            )
            session.commit()

    def bulk_update_quality_status(self, annotated_df: pd.DataFrame) -> int:
        """Batch-update quality_status for all rows in annotated_df that changed from OK."""
        if annotated_df.empty:
            return 0
        changed = annotated_df[annotated_df["quality_status"] != "OK"]
        if changed.empty:
            return 0
        updated = 0
        with self.db.session() as session:
            for _, row in changed.iterrows():
                session.execute(
                    update(OHLCVDailyRecord)
                    .where(
                        OHLCVDailyRecord.symbol == row["symbol"],
                        OHLCVDailyRecord.trading_date == row["trading_date"],
                        OHLCVDailyRecord.source == row["source"],
                    )
                    .values(quality_status=row["quality_status"])
                )
                updated += 1
            session.commit()
        return updated

    # ── Symbols ─────────────────────────────────────────────────────────────

    def upsert_symbols(self, df: pd.DataFrame) -> int:
        if df.empty:
            return 0
        records = [_coerce_symbol(r) for r in df.to_dict(orient="records")]
        inserted = 0
        with self.db.session() as session:
            for coerced in records:
                update_set = {k: v for k, v in coerced.items() if k not in ("symbol", "exchange", "source")}
                stmt = (
                    sqlite_insert(SymbolRecord)
                    .values(**coerced)
                    .on_conflict_do_update(
                        index_elements=["symbol", "exchange", "source"],
                        set_=update_set,
                    )
                )
                result = session.execute(stmt)
                inserted += result.rowcount
            session.commit()
        return inserted

    def query_symbols(self, exchange: str | None = None) -> pd.DataFrame:
        with self.db.session() as session:
            stmt = select(SymbolRecord)
            if exchange:
                stmt = stmt.where(SymbolRecord.exchange == exchange)
            rows = session.scalars(stmt).all()
        return _records_to_df(rows) if rows else pd.DataFrame()

    # ── Corporate Actions ────────────────────────────────────────────────────

    def insert_corporate_actions(self, df: pd.DataFrame) -> int:
        """Insert corporate actions; skip duplicates on (symbol, action_type, source, announcement_date)."""
        if df.empty:
            return 0
        records = [_coerce_ca(r) for r in df.to_dict(orient="records")]
        inserted = 0
        with self.db.session() as session:
            stmt = sqlite_insert(CorporateActionRecord).on_conflict_do_nothing(
                index_elements=["symbol", "action_type", "source", "announcement_date"]
            )
            session.execute(stmt, records)
            session.commit()
        return len(records)

    def query_corporate_actions(self, symbol: str | None = None) -> pd.DataFrame:
        with self.db.session() as session:
            stmt = select(CorporateActionRecord)
            if symbol:
                stmt = stmt.where(CorporateActionRecord.symbol == symbol)
            rows = session.scalars(stmt).all()
        return _records_to_df(rows) if rows else pd.DataFrame()

    # ── Data Quality Issues ──────────────────────────────────────────────────

    def insert_quality_issues(self, df: pd.DataFrame) -> int:
        if df.empty:
            return 0
        records = [_coerce_dqi(r) for r in df.to_dict(orient="records")]
        with self.db.session() as session:
            session.execute(sqlite_insert(DataQualityIssueRecord), records)
            session.commit()
        return len(records)

    def query_quality_issues(
        self,
        symbol: str | None = None,
        severity: str | None = None,
    ) -> pd.DataFrame:
        with self.db.session() as session:
            stmt = select(DataQualityIssueRecord)
            if symbol:
                stmt = stmt.where(DataQualityIssueRecord.symbol == symbol)
            if severity:
                stmt = stmt.where(DataQualityIssueRecord.severity == severity)
            rows = session.scalars(stmt).all()
        return _records_to_df(rows) if rows else pd.DataFrame()

    # ── Provider Reconciliation ──────────────────────────────────────────────

    def insert_reconciliation(self, df: pd.DataFrame) -> int:
        """Insert reconciliation rows; skip duplicates on the composite key."""
        if df.empty:
            return 0
        records = [_coerce_recon(r) for r in df.to_dict(orient="records")]
        with self.db.session() as session:
            stmt = sqlite_insert(ProviderReconciliationRecord).on_conflict_do_nothing(
                index_elements=["symbol", "trading_date", "field_name", "primary_source", "secondary_source"]
            )
            session.execute(stmt, records)
            session.commit()
        return len(records)

    def query_reconciliation(self, symbol: str | None = None) -> pd.DataFrame:
        with self.db.session() as session:
            stmt = select(ProviderReconciliationRecord)
            if symbol:
                stmt = stmt.where(ProviderReconciliationRecord.symbol == symbol)
            rows = session.scalars(stmt).all()
        return _records_to_df(rows) if rows else pd.DataFrame()

    # ── Liquidity Features ───────────────────────────────────────────────────

    def upsert_liquidity(self, df: pd.DataFrame) -> int:
        if df.empty:
            return 0
        records = [_coerce_liquidity(r) for r in df.to_dict(orient="records")]
        inserted = 0
        with self.db.session() as session:
            for coerced in records:
                update_set = {k: v for k, v in coerced.items() if k not in ("symbol", "trading_date")}
                stmt = (
                    sqlite_insert(LiquidityFeatureRecord)
                    .values(**coerced)
                    .on_conflict_do_update(
                        index_elements=["symbol", "trading_date"],
                        set_=update_set,
                    )
                )
                result = session.execute(stmt)
                inserted += result.rowcount
            session.commit()
        return inserted

    def query_liquidity(self, symbol: str) -> pd.DataFrame:
        with self.db.session() as session:
            stmt = (
                select(LiquidityFeatureRecord)
                .where(LiquidityFeatureRecord.symbol == symbol)
                .order_by(LiquidityFeatureRecord.trading_date)
            )
            rows = session.scalars(stmt).all()
        return _records_to_df(rows) if rows else pd.DataFrame()

    # ── Utility ──────────────────────────────────────────────────────────────

    def table_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        with self.db.session() as session:
            union = " UNION ALL ".join(
                f"SELECT '{t}' AS tbl, COUNT(*) AS cnt FROM {t}"
                for t in sorted(_ALLOWED_TABLES)
            )
            rows = session.execute(text(union)).fetchall()
            for tbl, cnt in rows:
                counts[tbl] = cnt or 0
        return counts


# ── Private helpers ──────────────────────────────────────────────────────────

def _records_to_df(rows: list[Any]) -> pd.DataFrame:
    data = []
    for r in rows:
        d = {c.name: getattr(r, c.name) for c in r.__table__.columns}
        data.append(d)
    return pd.DataFrame(data)


def _clean(row: dict[str, Any], allowed_keys: set[str]) -> dict[str, Any]:
    return {k: v for k, v in row.items() if k in allowed_keys}


_OHLCV_KEYS = {c.name for c in OHLCVDailyRecord.__table__.columns if c.name != "id"}
_SYMBOL_KEYS = {c.name for c in SymbolRecord.__table__.columns if c.name != "id"}
_CA_KEYS = {c.name for c in CorporateActionRecord.__table__.columns if c.name != "id"}
_DQI_KEYS = {c.name for c in DataQualityIssueRecord.__table__.columns if c.name != "id"}
_RECON_KEYS = {c.name for c in ProviderReconciliationRecord.__table__.columns if c.name != "id"}
_LIQ_KEYS = {c.name for c in LiquidityFeatureRecord.__table__.columns if c.name != "id"}


def _coerce_ohlcv(row: dict[str, Any]) -> dict[str, Any]:
    return _clean(row, _OHLCV_KEYS)


def _coerce_symbol(row: dict[str, Any]) -> dict[str, Any]:
    return _clean(row, _SYMBOL_KEYS)


def _coerce_ca(row: dict[str, Any]) -> dict[str, Any]:
    return _clean(row, _CA_KEYS)


def _coerce_dqi(row: dict[str, Any]) -> dict[str, Any]:
    return _clean(row, _DQI_KEYS)


def _coerce_recon(row: dict[str, Any]) -> dict[str, Any]:
    return _clean(row, _RECON_KEYS)


def _coerce_liquidity(row: dict[str, Any]) -> dict[str, Any]:
    return _clean(row, _LIQ_KEYS)
