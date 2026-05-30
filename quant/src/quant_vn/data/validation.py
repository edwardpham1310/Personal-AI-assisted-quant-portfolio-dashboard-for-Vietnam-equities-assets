"""Data validation and quality report generation."""

from __future__ import annotations

import datetime
import logging

import pandas as pd

from .models import DataQualityReport, ValidationIssue

logger = logging.getLogger(__name__)


def validate_ohlcv(df: pd.DataFrame, symbol: str) -> DataQualityReport:
    """
    Run data quality checks on a cleaned OHLCV DataFrame and return a report.

    This is non-destructive — it only reads the DataFrame and reports issues.
    Run this AFTER clean_ohlcv() to get an accurate picture of remaining problems.
    """
    issues: list[ValidationIssue] = []

    if df.empty:
        return DataQualityReport(
            symbol=symbol,
            total_rows=0,
            issues=[ValidationIssue(
                symbol=symbol,
                issue_type="empty_dataset",
                description="DataFrame is empty",
                severity="error",
            )],
        )

    df = df.copy()
    df["date"] = pd.to_datetime(df["date"]).dt.date

    total_rows = len(df)
    first_date = df["date"].min()
    last_date = df["date"].max()

    # Duplicates
    n_dupes = df["date"].duplicated().sum()
    if n_dupes > 0:
        issues.append(ValidationIssue(
            symbol=symbol,
            issue_type="duplicate_dates",
            description=f"{n_dupes} duplicate date(s) detected",
            severity="error",
        ))

    # Missing dates (business day gaps)
    full_range = pd.bdate_range(
        start=pd.Timestamp(first_date),
        end=pd.Timestamp(last_date),
    )
    actual_dates = set(df["date"])
    expected_dates = {d.date() for d in full_range}
    n_missing = len(expected_dates - actual_dates)

    if n_missing > 0:
        issues.append(ValidationIssue(
            symbol=symbol,
            issue_type="missing_dates",
            description=f"{n_missing} business day(s) missing between {first_date} and {last_date}",
            severity="warning",
        ))

    # OHLC relationship violations
    bad_ohlc = (
        (df["high"] < df["low"])
        | (df["high"] < df["open"])
        | (df["high"] < df["close"])
        | (df["low"] > df["open"])
        | (df["low"] > df["close"])
    )
    n_invalid_ohlc = bad_ohlc.sum()
    if n_invalid_ohlc > 0:
        bad_dates = df.loc[bad_ohlc, "date"].tolist()[:5]
        issues.append(ValidationIssue(
            symbol=symbol,
            issue_type="invalid_ohlc",
            description=f"{n_invalid_ohlc} row(s) with invalid OHLC relationship. Dates: {bad_dates}",
            severity="error",
        ))

    # Non-positive prices
    non_positive = (df[["open", "high", "low", "close"]] <= 0).any(axis=1).sum()
    if non_positive > 0:
        issues.append(ValidationIssue(
            symbol=symbol,
            issue_type="non_positive_price",
            description=f"{non_positive} row(s) with non-positive price",
            severity="error",
        ))

    # Zero volume days
    zero_vol = (df["volume"] == 0).sum()

    # Price spikes (>20% single-day)
    spike_threshold = 0.20
    close_ret = df["close"].pct_change().abs()
    spike_count = (close_ret > spike_threshold).sum()
    if spike_count > 0:
        issues.append(ValidationIssue(
            symbol=symbol,
            issue_type="price_spike",
            description=f"{spike_count} day(s) with >20% single-day close change (check for corporate actions or data errors)",
            severity="warning",
        ))

    # Null values
    null_counts = df[["open", "high", "low", "close", "volume"]].isnull().sum()
    for col, n in null_counts.items():
        if n > 0:
            issues.append(ValidationIssue(
                symbol=symbol,
                issue_type="null_values",
                description=f"{n} null value(s) in column '{col}'",
                severity="error",
            ))

    return DataQualityReport(
        symbol=symbol,
        total_rows=total_rows,
        first_date=first_date,
        last_date=last_date,
        missing_dates=n_missing,
        duplicate_rows=int(n_dupes),
        invalid_ohlc_rows=int(n_invalid_ohlc),
        zero_volume_days=int(zero_vol),
        price_spike_count=int(spike_count),
        issues=issues,
    )


def print_quality_report(report: DataQualityReport) -> None:
    """Print a human-readable quality report to stdout."""
    from rich.console import Console
    from rich.table import Table

    console = Console()
    console.print(f"\n[bold]Data Quality Report: {report.symbol}[/bold]")

    table = Table(show_header=True)
    table.add_column("Metric", style="cyan")
    table.add_column("Value", style="green")

    d = report.summary_dict()
    for k, v in d.items():
        if k not in ("symbol", "issues"):
            style = "red" if k == "has_errors" and v else None
            table.add_row(k.replace("_", " ").title(), str(v), style=style)

    console.print(table)

    if report.issues:
        console.print(f"\n[bold]Issues ({len(report.issues)}):[/bold]")
        for issue in report.issues:
            color = "red" if issue.severity == "error" else "yellow"
            console.print(f"  [{color}]{issue.severity.upper()}[/{color}] [{issue.issue_type}] {issue.description}")
    else:
        console.print("  [green]No issues found.[/green]")
