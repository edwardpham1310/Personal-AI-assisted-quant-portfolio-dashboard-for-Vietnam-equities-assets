# Data Pipeline Boundary

This directory defines a small, AI-agent-safe interface for the runtime data
pipeline. It is intentionally lightweight: agents should read schemas,
validation logic, and sample fixtures instead of opening real market data or
database files.

Data sources may include SSI FastConnect, VSDC, Vnstock, manual broker exports,
and local CSV imports. DuckDB and SQLite are runtime stores for local analytics,
portfolio state, and audit-friendly signal snapshots.

## Runtime Paths

- `data/raw/`: raw provider payloads and imported files.
- `data/processed/`: normalized parquet/csv exports and derived datasets.
- `data/cache/`: retry caches, downloaded metadata, and temporary artifacts.
- `data/samples/`: tiny non-sensitive samples only.
- `db/`: local DuckDB and SQLite database files.

Real DuckDB, SQLite, parquet, and large CSV files are runtime artifacts and must
not be committed. Agents must not inspect full raw market data files or database
files. Use `tests/fixtures/`, schemas, validation rules, and typed interfaces.

## Validation Scope

Validation should cover:

- Missing OHLCV values.
- Duplicate ticker/date rows.
- Invalid price values.
- Invalid volume values.
- Corporate action adjustments.
- Trading calendar alignment.
- Liquidity filters.
- Settlement delay assumptions.
- Tax, fee, and slippage assumptions.

For Vietnam market logic, do not hardcode uncertain financial assumptions. Add
a TODO with the source needed, or route the assumption through configuration.
