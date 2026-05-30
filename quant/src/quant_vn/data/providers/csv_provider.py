"""CSV data provider — imports local CSV files as OHLCV data."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from .base import AbstractDataProvider


# Default column name aliases for common Vietnam data source formats
_DEFAULT_COLUMN_MAP = {
    # date variants
    "ngay": "date",
    "trading_date": "date",
    "time": "date",
    "gio": "date",
    # price variants
    "gia_mo_cua": "open",
    "gia_cao_nhat": "high",
    "gia_thap_nhat": "low",
    "gia_dong_cua": "close",
    "gia_dieu_chinh": "close",
    "adjusted_close": "close",
    "mo_cua": "open",
    "cao_nhat": "high",
    "thap_nhat": "low",
    "dong_cua": "close",
    # volume variants
    "khoi_luong": "volume",
    "vol": "volume",
    "klgd": "volume",
    "trading_volume": "volume",
}


class CsvProvider(AbstractDataProvider):
    """
    Load OHLCV data from CSV files.

    Supports:
    - A single CSV file per symbol (e.g. data/raw/FPT.csv)
    - A directory of CSVs where each file is named <SYMBOL>.csv
    - A single CSV with a 'symbol' column containing multiple tickers

    column_map: optional dict to rename source columns → {date, open, high, low, close, volume}
    """

    def __init__(
        self,
        path: str | Path,
        column_map: dict[str, str] | None = None,
        date_format: str | None = None,
        symbol_col: str | None = "symbol",
    ):
        self.path = Path(path)
        self.column_map = {**_DEFAULT_COLUMN_MAP, **(column_map or {})}
        self.date_format = date_format
        self.symbol_col = symbol_col

    # ------------------------------------------------------------------
    def get_ohlcv(
        self,
        symbol: str,
        start_date: str,
        end_date: str,
        timeframe: str = "1d",
    ) -> pd.DataFrame:
        df = self._load_symbol(symbol.upper())
        df = self._filter_dates(df, start_date, end_date)
        return df

    def get_symbols(self, exchange: str | None = None) -> list[str]:
        if self.path.is_dir():
            return [f.stem.upper() for f in sorted(self.path.glob("*.csv"))]
        # single file: try to read symbol column
        try:
            sample = pd.read_csv(self.path, nrows=0)
            cols = [c.lower() for c in sample.columns]
            if self.symbol_col and self.symbol_col.lower() in cols:
                df = pd.read_csv(self.path, usecols=[self.symbol_col])
                return sorted(df[self.symbol_col].str.upper().unique().tolist())
        except Exception:
            pass
        return []

    # ------------------------------------------------------------------
    def _load_symbol(self, symbol: str) -> pd.DataFrame:
        if self.path.is_dir():
            candidates = [
                self.path / f"{symbol}.csv",
                self.path / f"{symbol.lower()}.csv",
            ]
            for c in candidates:
                if c.exists():
                    return self._read_and_normalise(c, symbol)
            raise FileNotFoundError(
                f"No CSV file found for symbol '{symbol}' in directory {self.path}"
            )

        # Single file with a symbol column
        df = self._read_and_normalise(self.path, symbol=None)
        if self.symbol_col and self.symbol_col.lower() in [c.lower() for c in df.columns]:
            sym_col = next(c for c in df.columns if c.lower() == self.symbol_col.lower())
            df = df[df[sym_col].str.upper() == symbol].drop(columns=[sym_col])
            if df.empty:
                raise ValueError(f"Symbol '{symbol}' not found in {self.path}")
        return df

    def _read_and_normalise(self, filepath: Path, symbol: str | None) -> pd.DataFrame:
        df = pd.read_csv(filepath, low_memory=False)
        df = self._rename_columns(df)
        df = self._parse_date(df)
        df = df.sort_values("date").reset_index(drop=True)

        required = {"date", "open", "high", "low", "close", "volume"}
        missing = required - set(df.columns)
        if missing:
            raise ValueError(
                f"CSV file {filepath} is missing required columns after mapping: {missing}. "
                f"Available columns: {list(df.columns)}. "
                f"Provide a column_map dict to map your column names."
            )

        # Cast numeric
        for col in ("open", "high", "low", "close"):
            df[col] = pd.to_numeric(df[col], errors="coerce")
        df["volume"] = pd.to_numeric(df["volume"], errors="coerce").fillna(0).astype(int)

        if symbol:
            df["symbol"] = symbol

        return df

    def _rename_columns(self, df: pd.DataFrame) -> pd.DataFrame:
        rename = {}
        for col in df.columns:
            lower = col.strip().lower()
            if lower in self.column_map:
                rename[col] = self.column_map[lower]
        return df.rename(columns=rename)

    def _parse_date(self, df: pd.DataFrame) -> pd.DataFrame:
        date_col = next((c for c in df.columns if c.lower() == "date"), None)
        if date_col is None:
            raise ValueError("No 'date' column found after column mapping.")
        if self.date_format:
            df[date_col] = pd.to_datetime(df[date_col], format=self.date_format)
        else:
            df[date_col] = pd.to_datetime(df[date_col], infer_datetime_format=True)
        df[date_col] = df[date_col].dt.date
        if date_col != "date":
            df = df.rename(columns={date_col: "date"})
        return df

    @staticmethod
    def _filter_dates(df: pd.DataFrame, start_date: str, end_date: str) -> pd.DataFrame:
        import datetime

        start = datetime.date.fromisoformat(start_date)
        end = datetime.date.fromisoformat(end_date)
        mask = (df["date"] >= start) & (df["date"] <= end)
        return df[mask].reset_index(drop=True)
