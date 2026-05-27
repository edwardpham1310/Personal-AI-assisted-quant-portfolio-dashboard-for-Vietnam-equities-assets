# Audit: Initial MVP Build — 2026-05-27

## What was built

Full MVP data pipeline for Vietnam stock market quantitative research.

### Architecture decisions

- SQLite via SQLAlchemy 2.x ORM as system-of-record. DuckDB for fast analytical queries via export.
- Pydantic v2 schemas for all normalized records — invalid rows are logged and excluded, never silently dropped.
- All rolling liquidity windows use `min_periods=window` — no partial-window leakage.
- Raw provider responses stored to disk in content-addressed paths before normalization. Unchanged hash → skip write.
- Duplicate OHLCV rows handled via `ON CONFLICT DO NOTHING` on `(symbol, trading_date, source)`.
- Corporate action fields (`announcement_date`, `ex_date`, `record_date`, `payment_date`) stored separately from price data — no automatic adjustment applied at this layer.

### Quant data integrity rules applied

1. Raw data preserved before any transformation.
2. Every normalized row carries `source` field.
3. Suspicious rows flagged with `quality_status`, never deleted.
4. Corporate action dates stored with all temporal fields — no future event data leaks into price history.
5. Adjusted close not invented — stored as `None` and `is_adjusted = False` when unavailable.
6. Reconciliation mismatches recorded in `provider_reconciliation` table, not silently resolved.
7. Tradable flag computation uses 20-day window with `min_periods=20` — no partial-window bias.

### Test coverage

67 tests passing. Coverage includes:
- OHLCV normalization (7 tests)
- Data validation (15 tests)
- Provider reconciliation (7 tests)
- Corporate actions (8 tests)
- Database storage (10 tests)
- Liquidity features (11 tests)
- CSV provider (5 tests)
- SSI provider contract (3 tests + 1 date format test)

### Known gaps for future work

- SSI intraday OHLCV — interface placeholder exists, not implemented
- VSDC HTML parser is regex-based fallback; requires BeautifulSoup for robust parsing
- Automatic corporate action price adjustment — belongs in backtest layer, not data layer
- No incremental update logic — re-ingestion deduplicates via hash, but no smart date-range gap detection
