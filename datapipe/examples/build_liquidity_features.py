"""Example: build liquidity features for all stored symbols."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from quant_vn_data.storage.database import get_db
from quant_vn_data.storage.sqlite_store import SQLiteStore
from quant_vn_data.market.liquidity import build_liquidity_features


def main():
    db = get_db()
    store = SQLiteStore(db)

    symbols_df = store.query_symbols()
    symbols = symbols_df["symbol"].tolist() if not symbols_df.empty else []

    if not symbols:
        print("No symbols in database. Run ingest_fpt.py first.")
        return

    total = 0
    for sym in symbols:
        df = store.query_ohlcv(sym)
        if df.empty:
            continue
        liq = build_liquidity_features(df)
        if not liq.empty:
            n = store.upsert_liquidity(liq)
            total += n
            tradable = liq["tradable_flag"].sum()
            bucket = liq["liquidity_bucket"].value_counts().to_dict()
            print(f"{sym}: {n} liquidity rows, {tradable} tradable days, buckets={bucket}")

    print(f"\nTotal: {total} liquidity feature rows built.")


if __name__ == "__main__":
    main()
