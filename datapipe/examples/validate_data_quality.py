"""Example: run data quality validation on stored OHLCV data."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from quant_vn_data.storage.database import get_db
from quant_vn_data.storage.sqlite_store import SQLiteStore
from quant_vn_data.validation.ohlcv_checks import validate_ohlcv
from quant_vn_data.validation.data_quality_report import generate_quality_report

import pandas as pd
from dataclasses import asdict


def main():
    db = get_db()
    store = SQLiteStore(db)

    symbols_df = store.query_symbols()
    symbols = symbols_df["symbol"].tolist() if not symbols_df.empty else ["FPT"]

    all_issues = []
    for sym in symbols:
        df = store.query_ohlcv(sym)
        if df.empty:
            continue
        _, issues = validate_ohlcv(df)
        all_issues.extend(issues)
        store.insert_quality_issues(pd.DataFrame([asdict(i) for i in issues]))
        print(f"{sym}: {len(issues)} issues")

    if all_issues:
        issues_df = pd.DataFrame([asdict(i) for i in all_issues])
        generate_quality_report(issues_df, output_path="reports/data_quality_report.csv")
    else:
        print("No issues found.")


if __name__ == "__main__":
    main()
