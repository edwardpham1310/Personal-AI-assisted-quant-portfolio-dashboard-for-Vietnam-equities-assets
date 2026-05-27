"""OHLCV data quality checks.

Each check returns a list of OHLCVIssue dicts.
validate_ohlcv() runs all checks and returns the combined list + an annotated DataFrame.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date
from enum import Enum
from typing import Any

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


class Severity(str, Enum):
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    INFO = "INFO"


@dataclass
class OHLCVIssue:
    symbol: str | None
    trading_date: date | None
    source: str | None
    issue_type: str
    severity: str
    field_name: str | None = None
    observed_value: str | None = None
    expected_rule: str | None = None
    message: str | None = None


def validate_ohlcv(
    df: pd.DataFrame,
    max_price_jump_pct: float = 15.0,
    min_close_price_vnd: float = 100.0,
    max_zero_volume_streak: int = 5,
    adjusted_close_drift_pct: float = 1.0,
) -> tuple[pd.DataFrame, list[OHLCVIssue]]:
    """Run all OHLCV validation checks.

    Returns:
        (annotated_df, issues_list)
        annotated_df has quality_status column updated.
        issues_list is ready to insert into data_quality_issues table.
    """
    if df.empty:
        return df, []

    df = df.copy()
    if "quality_status" not in df.columns:
        df["quality_status"] = "OK"

    issues: list[OHLCVIssue] = []

    def _issue(row: pd.Series, issue_type: str, severity: str, field: str, observed: Any, rule: str, msg: str) -> OHLCVIssue:
        return OHLCVIssue(
            symbol=row.get("symbol"),
            trading_date=row.get("trading_date"),
            source=row.get("source"),
            issue_type=issue_type,
            severity=severity,
            field_name=field,
            observed_value=str(observed) if observed is not None else None,
            expected_rule=rule,
            message=msg,
        )

    def _flag(mask: pd.Series, status: str) -> None:
        df.loc[mask, "quality_status"] = status

    for idx, row in df.iterrows():
        row_issues: list[OHLCVIssue] = []
        sym = row.get("symbol", "?")
        dt = row.get("trading_date")
        src = row.get("source", "?")

        o = row.get("open")
        h = row.get("high")
        l = row.get("low")
        c = row.get("close")
        v = row.get("volume")
        val = row.get("value")
        ceil = row.get("ceiling_price")
        floor = row.get("floor_price")
        adj = row.get("adjusted_close")

        # 1. Missing required fields
        for fname, fval in [("open", o), ("high", h), ("low", l), ("close", c)]:
            if fval is None or (isinstance(fval, float) and np.isnan(fval)):
                row_issues.append(_issue(row, "MISSING_FIELD", Severity.HIGH, fname, fval, "not null", f"{fname} is null"))

        if v is None:
            row_issues.append(_issue(row, "MISSING_FIELD", Severity.HIGH, "volume", v, "not null", "volume is null"))

        # 2. Non-positive prices
        for fname, fval in [("open", o), ("high", h), ("low", l), ("close", c)]:
            if fval is not None and not np.isnan(float(fval)) and float(fval) <= 0:
                row_issues.append(_issue(row, "NON_POSITIVE_PRICE", Severity.CRITICAL, fname, fval, "> 0", f"{fname} <= 0"))

        # 3. high < low
        if h is not None and l is not None and not np.isnan(float(h)) and not np.isnan(float(l)):
            if float(h) < float(l):
                row_issues.append(_issue(row, "HIGH_LESS_THAN_LOW", Severity.CRITICAL, "high", h, "high >= low", f"high={h} < low={l}"))

        # 4. open outside high/low
        if o is not None and h is not None and not (np.isnan(float(o)) or np.isnan(float(h))):
            if float(o) > float(h):
                row_issues.append(_issue(row, "OPEN_ABOVE_HIGH", Severity.CRITICAL, "open", o, "open <= high", f"open={o} > high={h}"))
        if o is not None and l is not None and not (np.isnan(float(o)) or np.isnan(float(l))):
            if float(o) < float(l):
                row_issues.append(_issue(row, "OPEN_BELOW_LOW", Severity.CRITICAL, "open", o, "open >= low", f"open={o} < low={l}"))

        # 5. close outside high/low
        if c is not None and h is not None and not (np.isnan(float(c)) or np.isnan(float(h))):
            if float(c) > float(h):
                row_issues.append(_issue(row, "CLOSE_ABOVE_HIGH", Severity.CRITICAL, "close", c, "close <= high", f"close={c} > high={h}"))
        if c is not None and l is not None and not (np.isnan(float(c)) or np.isnan(float(l))):
            if float(c) < float(l):
                row_issues.append(_issue(row, "CLOSE_BELOW_LOW", Severity.CRITICAL, "close", c, "close >= low", f"close={c} < low={l}"))

        # 6. Negative volume/value
        if v is not None and not np.isnan(float(v)) and float(v) < 0:
            row_issues.append(_issue(row, "NEGATIVE_VOLUME", Severity.CRITICAL, "volume", v, ">= 0", "volume < 0"))
        if val is not None and not np.isnan(float(val)) and float(val) < 0:
            row_issues.append(_issue(row, "NEGATIVE_VALUE", Severity.HIGH, "value", val, ">= 0", "value < 0"))

        # 7. Ceiling/floor breach
        if ceil is not None and c is not None and not np.isnan(float(ceil)) and not np.isnan(float(c)):
            if float(c) > float(ceil) * 1.001:  # small tolerance for rounding
                row_issues.append(_issue(row, "CEILING_BREACH", Severity.HIGH, "close", c, f"<= ceiling={ceil}", f"close {c} > ceiling {ceil}"))
        if floor is not None and c is not None and not np.isnan(float(floor)) and not np.isnan(float(c)):
            if float(c) < float(floor) * 0.999:
                row_issues.append(_issue(row, "FLOOR_BREACH", Severity.HIGH, "close", c, f">= floor={floor}", f"close {c} < floor {floor}"))

        # 8. Suspicious low close price
        if c is not None and not np.isnan(float(c)) and float(c) > 0 and float(c) < min_close_price_vnd:
            row_issues.append(_issue(row, "SUSPICIOUS_LOW_PRICE", Severity.MEDIUM, "close", c, f">= {min_close_price_vnd}", f"close {c} < {min_close_price_vnd} VND"))

        # 9. Zero volume flag (INFO level — may be valid holiday/halt)
        if v is not None and not np.isnan(float(v)) and float(v) == 0:
            row_issues.append(_issue(row, "ZERO_VOLUME", Severity.INFO, "volume", v, "> 0", "zero volume day"))

        # Determine worst severity for this row
        if row_issues:
            severities = [Severity.CRITICAL, Severity.HIGH, Severity.MEDIUM, Severity.LOW, Severity.INFO]
            row_severity = min(row_issues, key=lambda i: severities.index(Severity(i.severity))).severity
            df.at[idx, "quality_status"] = row_severity

        issues.extend(row_issues)

    # 10. Abnormal price jump (requires sorting by symbol/date)
    df = _check_price_jumps(df, issues, max_price_jump_pct)

    # 11. Adjusted close drift
    if "adjusted_close" in df.columns:
        _check_adj_drift(df, issues, adjusted_close_drift_pct)

    logger.info(
        "validate_ohlcv: %d rows, %d issues (%d critical)",
        len(df),
        len(issues),
        sum(1 for i in issues if i.severity == Severity.CRITICAL),
    )
    return df, issues


def _check_price_jumps(
    df: pd.DataFrame,
    issues: list[OHLCVIssue],
    max_pct: float,
) -> pd.DataFrame:
    df = df.sort_values(["symbol", "trading_date"]).copy()
    df["_prev_close"] = df.groupby("symbol")["close"].shift(1)
    mask = df["_prev_close"].notna() & df["close"].notna()
    df.loc[mask, "_jump_pct"] = (
        (df.loc[mask, "close"] - df.loc[mask, "_prev_close"]).abs()
        / df.loc[mask, "_prev_close"]
        * 100
    )
    suspicious = df["_jump_pct"] > max_pct
    for idx, row in df[suspicious].iterrows():
        issues.append(OHLCVIssue(
            symbol=row.get("symbol"),
            trading_date=row.get("trading_date"),
            source=row.get("source"),
            issue_type="ABNORMAL_PRICE_JUMP",
            severity=Severity.HIGH,
            field_name="close",
            observed_value=f"{row['_jump_pct']:.1f}%",
            expected_rule=f"daily move <= {max_pct}%",
            message=f"close changed {row['_jump_pct']:.1f}% from prior day",
        ))
        if df.at[idx, "quality_status"] == "OK":
            df.at[idx, "quality_status"] = Severity.HIGH

    df.drop(columns=["_prev_close", "_jump_pct"], errors="ignore", inplace=True)
    return df


def _check_adj_drift(
    df: pd.DataFrame,
    issues: list[OHLCVIssue],
    drift_pct: float,
) -> None:
    mask = df["adjusted_close"].notna() & df["close"].notna() & (df["close"] != 0)
    subset = df[mask].copy()
    subset["_drift"] = (subset["adjusted_close"] - subset["close"]).abs() / subset["close"] * 100
    suspicious = subset["_drift"] > drift_pct
    for _, row in subset[suspicious].iterrows():
        pct = row["_drift"]
        if pct >= 10.0:
            severity = Severity.HIGH
        elif pct >= 3.0:
            severity = Severity.MEDIUM
        else:
            severity = Severity.LOW
        issues.append(OHLCVIssue(
            symbol=row.get("symbol"),
            trading_date=row.get("trading_date"),
            source=row.get("source"),
            issue_type="ADJ_CLOSE_DRIFT",
            severity=severity,
            field_name="adjusted_close",
            observed_value=f"{pct:.2f}%",
            expected_rule=f"drift <= {drift_pct}%",
            message=f"adjusted_close differs from close by {pct:.2f}%",
        ))
