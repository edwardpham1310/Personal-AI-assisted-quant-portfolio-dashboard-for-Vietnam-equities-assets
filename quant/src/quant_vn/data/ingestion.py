"""High-level ingestion pipeline: provider → clean → store."""

from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

from .cleaning import clean_ohlcv
from .models import DataQualityReport
from .providers.base import AbstractDataProvider
from .storage import Database, PriceRepository
from .validation import validate_ohlcv

logger = logging.getLogger(__name__)


class IngestionPipeline:
    """
    Orchestrates: provider.get_ohlcv() → clean_ohlcv() → validate → upsert to DB.
    """

    def __init__(self, provider: AbstractDataProvider, db: Database):
        self.provider = provider
        self.db = db
        self.repo = PriceRepository(db)

    def ingest(
        self,
        symbol: str,
        start_date: str,
        end_date: str,
        exchange: str = "HOSE",
        is_adjusted: bool = False,
        fill_missing: bool = True,
        dry_run: bool = False,
    ) -> DataQualityReport:
        """
        Full ingestion for one symbol.
        Returns a DataQualityReport describing data quality after cleaning.
        """
        logger.info("Ingesting %s from %s via %s", symbol, self.provider.name, start_date)

        # 1. Fetch
        raw_df = self.provider.get_ohlcv(symbol, start_date, end_date)
        if raw_df.empty:
            logger.warning("Provider returned empty data for %s", symbol)
            return DataQualityReport(symbol=symbol, total_rows=0)

        # 2. Clean
        clean_df, issues = clean_ohlcv(
            raw_df,
            symbol=symbol,
            fill_missing=fill_missing,
            is_adjusted=is_adjusted,
        )

        # 3. Validate
        report = validate_ohlcv(clean_df, symbol=symbol)

        # 4. Store
        if not dry_run:
            n_written = self.repo.upsert_ohlcv(clean_df, exchange=exchange)
            logger.info("Stored %d rows for %s", n_written, symbol)
        else:
            logger.info("Dry run — skipping database write for %s", symbol)

        return report

    def ingest_many(
        self,
        symbols: list[str],
        start_date: str,
        end_date: str,
        exchange: str = "HOSE",
        is_adjusted: bool = False,
    ) -> dict[str, DataQualityReport]:
        """Ingest multiple symbols and return a dict of quality reports."""
        reports: dict[str, DataQualityReport] = {}
        for sym in symbols:
            try:
                reports[sym] = self.ingest(sym, start_date, end_date, exchange, is_adjusted)
            except Exception as exc:
                logger.error("Failed to ingest %s: %s", sym, exc)
                reports[sym] = DataQualityReport(
                    symbol=sym,
                    total_rows=0,
                    issues=[],
                )
        return reports

    def ingest_from_csv(
        self,
        path: str | Path,
        exchange: str = "HOSE",
        column_map: dict[str, str] | None = None,
        is_adjusted: bool = False,
    ) -> dict[str, DataQualityReport]:
        """
        Convenience method: ingest all CSVs from a directory or a single CSV.
        Uses CsvProvider internally.
        """
        from .providers.csv_provider import CsvProvider

        path = Path(path)
        provider = CsvProvider(path, column_map=column_map)
        symbols = provider.get_symbols()

        if not symbols:
            # Single file without symbol column — derive symbol from filename
            if path.is_file():
                symbols = [path.stem.upper()]
            else:
                logger.warning("No symbols found in %s", path)
                return {}

        reports: dict[str, DataQualityReport] = {}
        for sym in symbols:
            try:
                raw_df = provider.get_ohlcv(sym, "1900-01-01", "2099-12-31")
                clean_df, _ = clean_ohlcv(raw_df, symbol=sym, is_adjusted=is_adjusted)
                report = validate_ohlcv(clean_df, symbol=sym)
                n_written = self.repo.upsert_ohlcv(clean_df, exchange=exchange)
                logger.info("Stored %d rows for %s", n_written, sym)
                reports[sym] = report
            except Exception as exc:
                logger.error("Failed to ingest CSV for %s: %s", sym, exc)

        return reports
