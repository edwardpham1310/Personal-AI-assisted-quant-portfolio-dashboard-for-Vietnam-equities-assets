"""Example: ingest FPT daily OHLCV using CSV fallback (no API key required)."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from quant_vn_data.config import get_settings
from quant_vn_data.ingestion.ingest_ohlcv import ingest_ohlcv
from quant_vn_data.ingestion.raw_store import RawStore
from quant_vn_data.providers.csv_provider import CSVProvider
from quant_vn_data.storage.database import get_db
from quant_vn_data.storage.sqlite_store import SQLiteStore
from quant_vn_data.validation.ohlcv_checks import validate_ohlcv
from quant_vn_data.validation.data_quality_report import generate_quality_report
from quant_vn_data.market.liquidity import build_liquidity_features

import pandas as pd
from datetime import date
import logging

logging.basicConfig(level=logging.INFO, format="%(levelname)-8s %(message)s")


def create_sample_data(path: Path):
    """Create a minimal sample CSV for FPT if no real data is available."""
    import random
    random.seed(42)
    rows = []
    close = 86000.0
    for i in range(90):
        from datetime import timedelta
        d = date(2024, 1, 2) + timedelta(days=i)
        if d.weekday() >= 5:
            continue
        change = random.uniform(-0.05, 0.05)
        close = max(close * (1 + change), 10000)
        volume = random.randint(500_000, 3_000_000)
        rows.append({
            "date": d.isoformat(),
            "symbol": "FPT",
            "open": round(close * 0.99, 0),
            "high": round(close * 1.03, 0),
            "low": round(close * 0.97, 0),
            "close": round(close, 0),
            "volume": volume,
            "value": round(close * volume, 0),
        })
    df = pd.DataFrame(rows)
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False)
    print(f"Created sample data: {path} ({len(df)} rows)")


def main():
    settings = get_settings()

    # Use CSV provider (no API key needed)
    csv_path = Path("data/raw/sample/fpt_sample.csv")
    if not csv_path.exists():
        create_sample_data(csv_path)

    db = get_db()
    store = SQLiteStore(db)
    raw_store = RawStore(settings.raw_dir)

    provider = CSVProvider(csv_path, symbol="FPT", exchange="HOSE")

    print("\n--- Ingesting FPT OHLCV ---")
    count = ingest_ohlcv(provider, "FPT", "2024-01-01", "2024-12-31", store, raw_store=raw_store)
    print(f"Inserted: {count} rows")

    print("\n--- Querying OHLCV ---")
    df = store.query_ohlcv("FPT")
    print(df[["trading_date", "open", "high", "low", "close", "volume"]].tail(5).to_string())

    print("\n--- Running Validation ---")
    annotated, issues = validate_ohlcv(df)
    print(f"Issues found: {len(issues)}")
    if issues:
        generate_quality_report(pd.DataFrame([vars(i) for i in issues]))

    print("\n--- Building Liquidity Features ---")
    liq_df = build_liquidity_features(df)
    store.upsert_liquidity(liq_df)
    last = liq_df.dropna(subset=["tradable_flag"]).tail(1)
    if not last.empty:
        print(f"FPT liquidity: bucket={last['liquidity_bucket'].iloc[0]}, tradable={last['tradable_flag'].iloc[0]}")

    print("\n--- Database Counts ---")
    for t, n in store.table_counts().items():
        print(f"  {t}: {n}")

    print("\nDone!")


if __name__ == "__main__":
    main()
