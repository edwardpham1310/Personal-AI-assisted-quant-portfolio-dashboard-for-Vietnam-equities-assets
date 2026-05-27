"""Multi-source provider reconciliation.

Compares primary vs secondary provider OHLCV data by symbol/date,
flags mismatches, and returns reconciliation records ready for the DB.
"""

from __future__ import annotations

import logging
from typing import Any

import pandas as pd

logger = logging.getLogger(__name__)

_RECONCILIATION_STATUSES = {
    "MATCH": "MATCH",
    "MINOR_DIFFERENCE": "MINOR_DIFFERENCE",
    "MAJOR_DIFFERENCE": "MAJOR_DIFFERENCE",
    "MISSING_PRIMARY": "MISSING_PRIMARY",
    "MISSING_SECONDARY": "MISSING_SECONDARY",
    "UNVERIFIED": "UNVERIFIED",
}

_DEFAULT_TOLERANCES: dict[str, float] = {
    "close": 0.1,          # percent
    "volume": 1.0,
    "adjusted_close": 0.2,
    "reference_price": 0.1,
    "ceiling_price": 0.1,
    "floor_price": 0.1,
}


def reconcile_providers(
    primary_df: pd.DataFrame,
    secondary_df: pd.DataFrame,
    primary_source: str,
    secondary_source: str,
    fields: list[str] | None = None,
    tolerances: dict[str, float] | None = None,
) -> pd.DataFrame:
    """Compare two provider DataFrames on a per-symbol/date basis.

    Returns a DataFrame ready for SQLiteStore.insert_reconciliation().
    """
    compare_fields = fields or ["close", "volume", "adjusted_close"]
    tols = {**_DEFAULT_TOLERANCES, **(tolerances or {})}

    if primary_df.empty and secondary_df.empty:
        return pd.DataFrame()

    primary_df = _prep(primary_df, primary_source)
    secondary_df = _prep(secondary_df, secondary_source)

    # When one side is empty, synthesize the merge manually so we can mark MISSING_*
    if primary_df.empty:
        records: list[dict[str, Any]] = []
        for _, row in secondary_df.iterrows():
            for f in compare_fields:
                records.append(_make_record(
                    row.get("symbol"), row.get("trading_date"), f,
                    primary_source, secondary_source,
                    None, _get(row, f), None, None, tols.get(f, 0.1), "MISSING_PRIMARY",
                ))
        return pd.DataFrame(records)

    if secondary_df.empty:
        records = []
        for _, row in primary_df.iterrows():
            for f in compare_fields:
                records.append(_make_record(
                    row.get("symbol"), row.get("trading_date"), f,
                    primary_source, secondary_source,
                    _get(row, f), None, None, None, tols.get(f, 0.1), "MISSING_SECONDARY",
                ))
        return pd.DataFrame(records)

    # Merge on symbol + trading_date
    merged = primary_df.merge(
        secondary_df,
        on=["symbol", "trading_date"],
        how="outer",
        suffixes=("_pri", "_sec"),
    )

    records = []

    for _, row in merged.iterrows():
        sym = row.get("symbol")
        dt = row.get("trading_date")
        pri_present = not _is_missing(row, "close_pri") or not _is_missing(row, "volume_pri")
        sec_present = not _is_missing(row, "close_sec") or not _is_missing(row, "volume_sec")

        if not pri_present:
            for f in compare_fields:
                records.append(_make_record(
                    sym, dt, f, primary_source, secondary_source,
                    None, _get(row, f"{f}_sec"), None, None, tols.get(f, 0.1),
                    "MISSING_PRIMARY",
                ))
            continue

        if not sec_present:
            for f in compare_fields:
                records.append(_make_record(
                    sym, dt, f, primary_source, secondary_source,
                    _get(row, f"{f}_pri"), None, None, None, tols.get(f, 0.1),
                    "MISSING_SECONDARY",
                ))
            continue

        for f in compare_fields:
            pri_val = _get(row, f"{f}_pri")
            sec_val = _get(row, f"{f}_sec")

            if pri_val is None and sec_val is None:
                status = "UNVERIFIED"
                abs_diff = pct_diff = None
            elif pri_val is None or sec_val is None:
                status = "UNVERIFIED"
                abs_diff = pct_diff = None
            else:
                abs_diff = abs(float(pri_val) - float(sec_val))
                base = float(pri_val) if float(pri_val) != 0 else 1.0
                pct_diff = abs_diff / abs(base) * 100
                tol = tols.get(f, 0.1)
                if pct_diff <= tol:
                    status = "MATCH"
                elif pct_diff <= tol * 10:
                    status = "MINOR_DIFFERENCE"
                else:
                    status = "MAJOR_DIFFERENCE"

            records.append(_make_record(
                sym, dt, f, primary_source, secondary_source,
                pri_val, sec_val, abs_diff, pct_diff, tols.get(f, 0.1), status,
            ))

    result = pd.DataFrame(records)
    logger.info(
        "Reconciled %d symbol-date pairs: %s",
        len(merged),
        result["status"].value_counts().to_dict() if not result.empty else {},
    )
    return result


def _prep(df: pd.DataFrame, source: str) -> pd.DataFrame:
    if df.empty:
        return df
    df = df.copy()
    key_cols = [c for c in ["symbol", "trading_date"] if c in df.columns]
    extra_cols = [c for c in df.columns if c not in key_cols]
    df = df[key_cols + extra_cols]
    if "trading_date" in df.columns:
        df["trading_date"] = pd.to_datetime(df["trading_date"]).dt.date
    return df


def _is_missing(row: pd.Series, col: str) -> bool:
    v = row.get(col)
    return v is None or (isinstance(v, float) and pd.isna(v))


def _get(row: pd.Series, col: str) -> float | None:
    v = row.get(col)
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    return float(v)


def _make_record(
    symbol: Any, trading_date: Any, field_name: str,
    primary_source: str, secondary_source: str,
    primary_value: float | None, secondary_value: float | None,
    abs_diff: float | None, pct_diff: float | None,
    tolerance: float, status: str,
) -> dict[str, Any]:
    return {
        "symbol": symbol,
        "trading_date": trading_date,
        "field_name": field_name,
        "primary_source": primary_source,
        "secondary_source": secondary_source,
        "primary_value": primary_value,
        "secondary_value": secondary_value,
        "absolute_difference": abs_diff,
        "percentage_difference": pct_diff,
        "tolerance": tolerance,
        "status": status,
    }
