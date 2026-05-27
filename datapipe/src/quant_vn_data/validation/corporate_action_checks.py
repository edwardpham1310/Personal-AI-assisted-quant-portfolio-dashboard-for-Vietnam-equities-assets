"""Corporate action validation checks."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date

import pandas as pd

from .ohlcv_checks import OHLCVIssue, Severity

logger = logging.getLogger(__name__)


def validate_corporate_actions(
    df: pd.DataFrame,
    suspicious_cash_dividend_vnd: float = 100_000.0,
    suspicious_stock_ratio: float = 2.0,
) -> list[OHLCVIssue]:
    """Validate corporate action records. Returns list of issues."""
    issues: list[OHLCVIssue] = []

    for _, row in df.iterrows():
        sym = row.get("symbol")
        ann = row.get("announcement_date")
        rec = row.get("record_date")
        act = row.get("action_type")

        # 1. No symbol
        if not sym:
            issues.append(OHLCVIssue(
                symbol=None, trading_date=None, source=row.get("source"),
                issue_type="CA_MISSING_SYMBOL", severity=Severity.HIGH,
                message="Corporate action without symbol",
            ))

        # 2. No action type
        if not act or act == "UNKNOWN":
            issues.append(OHLCVIssue(
                symbol=sym, trading_date=ann, source=row.get("source"),
                issue_type="CA_MISSING_ACTION_TYPE", severity=Severity.MEDIUM,
                message="Corporate action has no parseable action type",
            ))

        # 3. Date ordering: announcement <= record <= ex <= payment
        ann_d = _to_date(ann)
        rec_d = _to_date(rec)
        ex_d = _to_date(row.get("ex_date"))
        pay_d = _to_date(row.get("payment_date"))

        date_pairs = [
            ("announcement_date", "record_date", ann_d, rec_d, "CA_RECORD_BEFORE_ANNOUNCEMENT"),
            ("record_date", "ex_date", rec_d, ex_d, "CA_EX_BEFORE_RECORD"),
            ("ex_date", "payment_date", ex_d, pay_d, "CA_PAYMENT_BEFORE_EX"),
        ]
        for earlier_name, later_name, earlier_d, later_d, issue_type in date_pairs:
            if earlier_d and later_d and later_d < earlier_d:
                issues.append(OHLCVIssue(
                    symbol=sym, trading_date=ann, source=row.get("source"),
                    issue_type=issue_type, severity=Severity.HIGH,
                    field_name=later_name,
                    observed_value=str(later_d),
                    expected_rule=f">= {earlier_name}={earlier_d}",
                    message=f"{later_name} {later_d} precedes {earlier_name} {earlier_d}",
                ))

        # 4. Suspicious cash dividend
        cash_div = row.get("cash_dividend")
        if cash_div is not None and float(cash_div) > suspicious_cash_dividend_vnd:
            issues.append(OHLCVIssue(
                symbol=sym, trading_date=ann, source=row.get("source"),
                issue_type="CA_SUSPICIOUS_DIVIDEND", severity=Severity.MEDIUM,
                field_name="cash_dividend",
                observed_value=str(cash_div),
                expected_rule=f"<= {suspicious_cash_dividend_vnd}",
                message=f"cash dividend {cash_div} VND/share seems very high",
            ))

        # 5. Suspicious or invalid stock ratio
        for field in ("stock_dividend_ratio", "bonus_share_ratio", "split_ratio"):
            ratio = row.get(field)
            if ratio is None:
                continue
            ratio_f = float(ratio)
            if ratio_f <= 0:
                issues.append(OHLCVIssue(
                    symbol=sym, trading_date=ann, source=row.get("source"),
                    issue_type="CA_INVALID_RATIO", severity=Severity.HIGH,
                    field_name=field,
                    observed_value=str(ratio),
                    expected_rule="> 0",
                    message=f"{field}={ratio} must be positive",
                ))
            elif ratio_f > suspicious_stock_ratio:
                issues.append(OHLCVIssue(
                    symbol=sym, trading_date=ann, source=row.get("source"),
                    issue_type="CA_SUSPICIOUS_RATIO", severity=Severity.MEDIUM,
                    field_name=field,
                    observed_value=str(ratio),
                    expected_rule=f"<= {suspicious_stock_ratio}",
                    message=f"{field}={ratio} is unusually high",
                ))

        # 6. Unparsed raw
        if row.get("parse_status") in ("RAW_ONLY", "UNPARSED"):
            issues.append(OHLCVIssue(
                symbol=sym, trading_date=ann, source=row.get("source"),
                issue_type="CA_UNPARSED_EVENT", severity=Severity.LOW,
                message="Corporate action stored as raw text only — not fully parsed",
            ))

    return issues


def _to_date(v: object) -> date | None:
    if isinstance(v, date):
        return v
    try:
        from datetime import datetime
        return datetime.strptime(str(v)[:10], "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None
