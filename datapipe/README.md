# quant-vn-data

Vietnam stock market data pipeline for quantitative research.

Ingests OHLCV data from SSI FastConnect, Vnstock, and CSV files. Validates data quality, reconciles providers, stores normalized records in SQLite, and exports analytical views to DuckDB.

**Disclaimer:** This software is for research only. It is not financial advice. Data may contain errors. Always verify before using real money.

---

## Why data quality matters in Vietnam quant trading

Vietnam stocks trade on HOSE, HNX, and UPCoM. Market characteristics that must be handled correctly:

- **Price limits:** HOSE ±7%, HNX ±10%, UPCoM ±15% from reference price daily
- **Liquidity varies hugely:** VN30 blue chips trade billions of VND daily; many small-caps trade zero volume on some days
- **Corporate actions are frequent:** cash dividends, stock dividends, rights issues, splits — all must be captured accurately or backtests will produce false results
- **Adjusted prices matter:** never invent them; always mark `is_adjusted = false` when unadjusted

A backtest built on bad data is worse than no backtest at all.

---

## Data providers

| Provider | Purpose | Credentials |
|---|---|---|
| SSI FastConnect | Primary OHLCV, symbols, indexes | `SSI_CONSUMER_ID` + `SSI_CONSUMER_SECRET` |
| VSDC | Corporate actions | No key (public web) |
| Vnstock | Research / fallback OHLCV | `pip install vnstock` |
| CSV | Local development / offline testing | None |

---

## Setup

### 1. Install

```bash
pip install -e ".[dev]"
```

For Vnstock support:

```bash
pip install -e ".[dev,vnstock]"
```

### 2. Configure

```bash
cp .env.example .env
# Edit .env with your SSI API credentials
```

`.env` fields:

```env
SSI_CONSUMER_ID=your_id
SSI_CONSUMER_SECRET=your_secret
SSI_BASE_URL=https://fc-data.ssi.com.vn
DATA_DIR=./data
DATABASE_URL=sqlite:///data/database/quant_vn_data.sqlite
DUCKDB_PATH=./data/database/quant_vn_data.duckdb
```

### 3. Initialize database

```bash
quant-vn-data db init
```

---

## Ingest your first ticker

### Using SSI (requires API key)

```bash
quant-vn-data ingest-ohlcv --provider ssi --symbol FPT --start 2020-01-01 --end 2026-05-27
```

### Using Vnstock fallback

```bash
quant-vn-data ingest-ohlcv --provider vnstock --symbol FPT --start 2020-01-01 --end 2026-05-27
```

### Using CSV (no credentials)

```bash
quant-vn-data import-csv --path data/raw/sample_fpt.csv --symbol FPT --exchange HOSE
```

### End-to-end example (no API key needed)

```bash
python examples/ingest_fpt.py
```

---

## Validate data

```bash
quant-vn-data validate --symbol FPT
quant-vn-data quality-report --output reports/data_quality_report.csv
```

Checks run:

- Missing open/high/low/close
- high < low, open > high, close > high, etc.
- Negative volume/value
- Ceiling and floor price breaches (Vietnam market-specific)
- Abnormal day-over-day price jumps (>15% by default)
- Zero-volume days
- Adjusted close drift vs unadjusted close

Severity levels: `CRITICAL` → `HIGH` → `MEDIUM` → `LOW` → `INFO`

---

## Reconcile SSI vs Vnstock

```bash
# First ingest both sources for the same symbol
quant-vn-data ingest-ohlcv --provider ssi --symbol FPT --start 2024-01-01 --end 2024-12-31
quant-vn-data ingest-ohlcv --provider vnstock --symbol FPT --start 2024-01-01 --end 2024-12-31

# Then reconcile
quant-vn-data reconcile --symbol FPT --primary ssi --secondary vnstock
```

Statuses: `MATCH` | `MINOR_DIFFERENCE` | `MAJOR_DIFFERENCE` | `MISSING_PRIMARY` | `MISSING_SECONDARY`

---

## Build liquidity features

```bash
quant-vn-data build-liquidity --symbol FPT
quant-vn-data build-liquidity --all
```

Features computed per symbol/date:

| Feature | Description |
|---|---|
| `avg_volume_20d` | 20-day rolling average volume |
| `avg_value_20d` | 20-day rolling average traded value (VND) |
| `zero_volume_days_20d` | Count of zero-volume days in 20-day window |
| `limit_up_days_20d` | Count of ceiling-price days in 20-day window |
| `tradable_flag` | True if meets all tradability filters |
| `liquidity_bucket` | HIGH / MEDIUM / LOW / UNTRADABLE |

**Tradable filter defaults:**
- `avg_value_20d >= 5,000,000,000 VND`
- `zero_volume_days_20d <= 2`
- `close >= 5,000 VND`
- No CRITICAL data quality issues

**Liquidity buckets:**
- HIGH: avg_value_20d ≥ 100 bn VND
- MEDIUM: 20–100 bn VND
- LOW: 5–20 bn VND
- UNTRADABLE: < 5 bn VND

---

## Export to DuckDB

```bash
quant-vn-data export-duckdb
```

Creates analytical views:

- `v_ohlcv_clean` — OHLCV without CRITICAL issues
- `v_ohlcv_tradable` — OHLCV joined with tradable liquidity
- `v_liquidity_latest` — latest liquidity snapshot per symbol
- `v_data_quality_summary` — issue counts by symbol/severity/type
- `v_provider_mismatches` — all rows with MINOR or MAJOR differences

---

## Ingest symbols

```bash
quant-vn-data ingest-symbols --provider ssi --exchange HOSE
```

---

## Ingest a watchlist

```bash
quant-vn-data ingest-watchlist --provider ssi --start 2020-01-01 --end 2026-05-27
```

Edit `config/watchlist.yaml` to customize your symbol list.

---

## Database schema

### `ohlcv_daily`
Primary OHLCV table. Unique on `(symbol, trading_date, source)`.

Key columns: `open`, `high`, `low`, `close`, `adjusted_close`, `volume`, `value`, `reference_price`, `ceiling_price`, `floor_price`, `foreign_buy_volume`, `foreign_sell_volume`, `quality_status`, `source`, `is_adjusted`

### `symbols`
Security master. Unique on `(symbol, exchange, source)`.

### `corporate_actions`
Cash dividends, stock dividends, rights issues, splits, consolidations.

Key columns: `announcement_date`, `record_date`, `ex_date`, `payment_date`, `action_type`, `cash_dividend`, `stock_dividend_ratio`, `split_ratio`

### `data_quality_issues`
All flagged issues from validation. Severity: CRITICAL / HIGH / MEDIUM / LOW / INFO.

### `provider_reconciliation`
Per-field comparisons between primary and secondary sources.

### `liquidity_features`
Rolling liquidity metrics and tradability flags. Unique on `(symbol, trading_date)`.

---

## Run tests

```bash
make test
# or
python3 -m pytest tests/ -v
```

82 tests covering: OHLCV normalization, data validation, provider reconciliation, corporate actions, database storage, liquidity features, CSV provider, SSI provider contract, raw store, DuckDB export.

---

## Known limitations

- SSI FastConnect API endpoint paths are based on documented v2 API. If SSI changes their API, update `ssi_fastconnect.py`.
- VSDC HTML parser is best-effort. If VSDC changes their page structure, update `vsdc.py`.
- Vietnam public holidays are hardcoded through 2026. Update `calendar.py` annually.
- Adjusted close is stored as provided by the data source. No automatic corporate-action adjustment is computed (that belongs in a future strategy layer).
- Intraday OHLCV is not yet implemented.

---

## Future roadmap

1. **Backtesting engine** — no-lookahead vectorized backtester with T+1 execution
2. **Strategy research** — momentum, mean reversion, factor models
3. **Corporate action adjustment** — automatic close price adjustment using ex_date and ratio
4. **ML price prediction** — feature engineering pipeline, XGBoost / LightGBM baseline
5. **Portfolio optimization** — mean-variance, risk parity, constraints for Vietnam market
6. **Live broker integration** — SSI iBoard / DNSE order execution

---

## Project structure

```
quant-vn-data/
  src/quant_vn_data/
    config/          # Settings (pydantic-settings) + YAML loaders
    providers/       # SSI, VSDC, Vnstock, CSV provider implementations
    ingestion/       # Orchestration: raw store + normalize + upsert
    normalization/   # Pydantic schemas + column mapping
    storage/         # SQLite ORM + DuckDB export
    validation/      # OHLCV checks + corporate action checks + reconciliation
    market/          # Calendar, universe, liquidity, price limits
    cli.py           # Typer CLI
  config/            # YAML config files (providers, liquidity, validation, watchlist)
  tests/             # 67 pytest tests
  examples/          # Runnable workflow scripts
  data/              # Raw + processed + database (gitignored)
```
