"""Generate data quality summary reports from quality issues stored in SQLite."""

from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)


def generate_quality_report(
    issues_df: pd.DataFrame,
    output_path: str | Path | None = None,
) -> pd.DataFrame:
    """Summarize quality issues and optionally write a CSV report.

    Returns a summary DataFrame grouped by (symbol, severity, issue_type).
    """
    if issues_df.empty:
        logger.info("No data quality issues to report.")
        return pd.DataFrame()

    summary = (
        issues_df.groupby(["symbol", "severity", "issue_type"], dropna=False)
        .size()
        .reset_index(name="count")
        .sort_values(["symbol", "severity", "issue_type"])
    )

    _print_console_summary(issues_df, summary)

    if output_path:
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        issues_df.to_csv(path, index=False)
        logger.info("Quality report written to %s (%d rows)", path, len(issues_df))

    return summary


def _print_console_summary(full: pd.DataFrame, summary: pd.DataFrame) -> None:
    total = len(full)
    by_severity = full["severity"].value_counts().to_dict()

    print("\n" + "=" * 60)
    print("DATA QUALITY REPORT")
    print("=" * 60)
    print(f"Total issues : {total}")
    for sev in ["CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"]:
        count = by_severity.get(sev, 0)
        if count:
            print(f"  {sev:<10}: {count}")
    print()

    if not summary.empty:
        top = summary.head(20)
        print("Top issues by (symbol, severity, type):")
        for _, row in top.iterrows():
            print(f"  {row['symbol']:<10} {row['severity']:<10} {row['issue_type']:<35} {row['count']}")
    print("=" * 60 + "\n")
