"""DuckDB analytics layer — export from SQLite and create analytical views."""

from __future__ import annotations

import logging
from pathlib import Path

import duckdb
import pandas as pd

logger = logging.getLogger(__name__)


class DuckDBStore:
    def __init__(self, duckdb_path: str | Path) -> None:
        self.path = Path(duckdb_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def _connect(self) -> duckdb.DuckDBPyConnection:
        return duckdb.connect(str(self.path))

    def export_from_sqlite(self, sqlite_path: str) -> None:
        """Attach SQLite database and copy all tables into DuckDB.

        Uses a temp-table-then-rename pattern so existing data survives a crash
        during the copy.
        """
        abs_sqlite = str(Path(sqlite_path).resolve())
        tables = [
            "symbols",
            "ohlcv_daily",
            "corporate_actions",
            "provider_reconciliation",
            "data_quality_issues",
            "liquidity_features",
        ]
        with self._connect() as con:
            con.execute(f"ATTACH '{abs_sqlite}' AS src (TYPE SQLITE)")
            for table in tables:
                tmp = f"_tmp_{table}"
                try:
                    con.execute(f"DROP TABLE IF EXISTS {tmp}")
                    con.execute(f"CREATE TABLE {tmp} AS SELECT * FROM src.{table}")
                    count = con.execute(f"SELECT COUNT(*) FROM {tmp}").fetchone()[0]
                    con.execute(f"DROP TABLE IF EXISTS {table}")
                    con.execute(f"ALTER TABLE {tmp} RENAME TO {table}")
                    logger.info("Exported %s rows into DuckDB table %s", count, table)
                except Exception as exc:
                    logger.warning("Failed to export table %s: %s", table, exc)
                    con.execute(f"DROP TABLE IF EXISTS {tmp}")
            con.execute("DETACH src")
            self._create_views(con)

    def write_dataframe(self, table: str, df: pd.DataFrame, overwrite: bool = True) -> None:
        """Write a pandas DataFrame directly into DuckDB."""
        with self._connect() as con:
            if overwrite:
                con.execute(f"DROP TABLE IF EXISTS {table}")
            con.execute(f"CREATE TABLE IF NOT EXISTS {table} AS SELECT * FROM df")

    def query(self, sql: str) -> pd.DataFrame:
        with self._connect() as con:
            return con.execute(sql).df()

    def _create_views(self, con: duckdb.DuckDBPyConnection) -> None:
        views = {
            "v_ohlcv_clean": """
                CREATE OR REPLACE VIEW v_ohlcv_clean AS
                SELECT * FROM ohlcv_daily
                WHERE quality_status NOT IN ('CRITICAL')
                ORDER BY symbol, trading_date
            """,
            "v_ohlcv_tradable": """
                CREATE OR REPLACE VIEW v_ohlcv_tradable AS
                SELECT o.*
                FROM ohlcv_daily o
                JOIN liquidity_features l
                  ON o.symbol = l.symbol AND o.trading_date = l.trading_date
                WHERE l.tradable_flag = TRUE
                  AND o.quality_status NOT IN ('CRITICAL')
                ORDER BY o.symbol, o.trading_date
            """,
            "v_liquidity_latest": """
                CREATE OR REPLACE VIEW v_liquidity_latest AS
                SELECT l.*
                FROM liquidity_features l
                INNER JOIN (
                    SELECT symbol, MAX(trading_date) AS max_date
                    FROM liquidity_features
                    GROUP BY symbol
                ) m ON l.symbol = m.symbol AND l.trading_date = m.max_date
            """,
            "v_data_quality_summary": """
                CREATE OR REPLACE VIEW v_data_quality_summary AS
                SELECT
                    symbol,
                    severity,
                    issue_type,
                    COUNT(*) AS issue_count,
                    MAX(created_at) AS last_seen
                FROM data_quality_issues
                GROUP BY symbol, severity, issue_type
                ORDER BY symbol, severity
            """,
            "v_provider_mismatches": """
                CREATE OR REPLACE VIEW v_provider_mismatches AS
                SELECT * FROM provider_reconciliation
                WHERE status IN ('MAJOR_DIFFERENCE', 'MINOR_DIFFERENCE')
                ORDER BY symbol, trading_date
            """,
        }
        for name, sql in views.items():
            try:
                con.execute(sql)
                logger.debug("Created DuckDB view: %s", name)
            except Exception as exc:
                logger.warning("Could not create view %s: %s", name, exc)

    def table_counts(self) -> dict[str, int]:
        tables = [
            "symbols", "ohlcv_daily", "corporate_actions",
            "provider_reconciliation", "data_quality_issues", "liquidity_features",
        ]
        counts: dict[str, int] = {}
        with self._connect() as con:
            for t in tables:
                try:
                    row = con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()
                    counts[t] = row[0] if row else 0
                except Exception:
                    counts[t] = -1
        return counts
