# Audit: Strict Review Fixes — 2026-05-27

## What was reviewed

Specialist review (QA / Reality Checker / Data Engineer / Quant Researcher) covering 15 problem areas. 30+ issues identified across security, data engineering, quant correctness, and code quality.

## Fixes implemented

### CRITICAL

- **CA dedup guard** (`migrations.py`): Added `UniqueConstraint` on `(symbol, action_type, source, announcement_date)` so re-ingest never duplicates corporate actions.
- **Reconciliation dedup guard** (`migrations.py`): Added `UniqueConstraint` on the composite reconciliation key.
- **_update_quality_status stub** (`cli.py`): Implemented using `store.bulk_update_quality_status()` — quality_status is now written back to `ohlcv_daily` after validation.
- **_read_meta silent failure** (`raw_store.py`): Now logs WARNING instead of silently returning None when meta.json exists but is unreadable.

### HIGH — Security

- **SSI credential leak** (`ssi_fastconnect.py`): Token error message now only exposes safe keys (`status`, `message`, `code`, `errorCode`), not the full response body.
- **Path traversal** (`raw_store.py`): `_safe_component()` validates provider/dataset/symbol with an allow-list regex before constructing disk paths.
- **Secret redaction in meta.json** (`raw_store.py`): `consumerID`, `consumerSecret`, `apiKey`, `token`, `password`, `secret` are replaced with `***` in request_params.
- **HTTPS enforcement** (`ssi_fastconnect.py`): `__init__` raises `ProviderError` if `base_url` does not start with `https://`.
- **DB path in config show** (`cli.py`): `DATABASE_URL` and `DUCKDB_PATH` display `<redacted>` instead of literal file paths.

### HIGH — Data correctness

- **SSI column aliases** (`normalize_ohlcv.py`): Added `TradingDate`, `OpenPrice`, `HighPrice`, `LowPrice`, `ClosePrice`, `TotalVolume`, `TotalValue`, `Symbol`, and foreign flow variants.
- **Partial pagination silent return** (`ssi_fastconnect.py`): HTTP errors during pagination now propagate via `ProviderError` instead of breaking out of the loop with partial data.
- **Watchlist path bug** (`cli.py`): `--watchlist` now loads the exact file specified (full path), not `Path(watchlist).parent / "watchlist.yaml"`.
- **bulk_update_quality_status** (`sqlite_store.py`): New method batch-updates `quality_status` for all non-OK rows; used by the `validate` CLI command.
- **Bulk OHLCV upsert** (`sqlite_store.py`): Replaced row-by-row Python loop with single `session.execute(stmt, records)` executemany call; duplicate detection via `before/after COUNT(*)`.
- **DuckDB atomic export** (`duckdb_store.py`): Uses temp-table-then-rename (`_tmp_{table}` → `{table}`) so existing data survives a crash during copy.
- **DuckDB SQLite absolute path** (`duckdb_store.py`): `Path(sqlite_path).resolve()` called before ATTACH — works correctly regardless of CWD.
- **CA date ordering** (`corporate_action_checks.py`): Full ordering check across all four dates: `announcement ≤ record ≤ ex ≤ payment`. Previously only checked `record < announcement`.
- **Zero/negative CA ratios** (`corporate_action_checks.py`): Added `CA_INVALID_RATIO` HIGH issue for `stock_dividend_ratio`, `bonus_share_ratio`, `split_ratio` ≤ 0.
- **Unknown exchange** (`price_limits.py`): `compute_price_limits` raises `ValueError` for unrecognised exchange codes. `enrich_price_limits` catches and logs WARNING, returns null limits instead of silently applying wrong HOSE 7% limit.
- **Null volume severity** (`ohlcv_checks.py`): Raised from MEDIUM to HIGH — null volume has the same downstream impact as null price.
- **Tiered adj_close drift** (`ohlcv_checks.py`): Severity now tiers by magnitude: ≥10% = HIGH, ≥3% = MEDIUM, else LOW (was always LOW).

### MEDIUM

- **NaN check** (`schemas.py`): Replaced `v != v` with explicit `isinstance(v, float) and math.isnan(v)`.
- **datetime.utcnow()** (`raw_store.py`): Replaced deprecated `datetime.utcnow()` with `datetime.now(timezone.utc)`.
- **normalize row failure log level** (`normalize_ohlcv.py`): Raised from DEBUG to WARNING.
- **database.py dir creation order** (`database.py`): `_ensure_database_dir` now called before `Database()` / `create_engine`.

### Structural

- **_ALLOWED_TABLES frozenset** (`sqlite_store.py`): SQL table names in `table_counts` are drawn from the frozenset, not formatted from user input.
- **insert_reconciliation dedup** (`sqlite_store.py`): Now uses `on_conflict_do_nothing` matching the new unique constraint.

## Tests added

15 new tests across 3 new test files:

- `tests/test_raw_store.py` (9 tests): store/read, hash dedup, changed-data re-write, secret redaction, path traversal rejection, meta.json structure.
- `tests/test_duckdb_store.py` (4 tests): export, idempotency, views, relative path resolution.
- `tests/test_database_storage.py` (+2 tests): `bulk_update_quality_status` write-back; OK-rows skipped.

## Final test count

82/82 passing (was 67/67 before this review).

## Remaining known gaps

- `is_adjusted` propagation: currently always `False` even for providers that return adjusted prices. Requires ingest-layer change.
- Price jump false positives on ex_dates: `_check_price_jumps` does not yet accept `ex_dates` set to suppress corporate-action-day jumps.
- SSI intraday OHLCV: interface placeholder only.
- VSDC HTML parser: regex fallback; no BeautifulSoup structural parsing.
- Minimum history requirement in `build_liquidity_features`: `tradable_flag` can be True after only 20 days.
- Reconciliation zero-price guard: zero primary_value uses 1.0 substitute, producing misleading pct_diff.
