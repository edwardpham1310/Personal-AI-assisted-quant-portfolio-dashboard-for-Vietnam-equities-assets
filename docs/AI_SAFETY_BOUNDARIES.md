# Quant Project AI Safety Boundaries

These boundaries protect this personal quant portfolio dashboard from unsafe
agent behavior, accidental credential exposure, and premature trading features.

## Protected Areas

- SSI trading credentials.
- SSI live order placement.
- Order execution modules.
- Auto-trading toggle.
- Password gate.
- Audit log.
- Portfolio accounting.
- Fee/tax/slippage calculations.
- DuckDB/SQLite schema migrations.
- Real market data ingestion.

## Rules

- Read-only market data integration is allowed only when requested.
- Order preview is allowed only in the trading-read-only/order-preview phase.
- Live order placement is forbidden unless the current phase explicitly allows
  it.
- Auto-trading is forbidden until all prior safety phases are complete.
- Mock data must not replace real SSI data when the phase requires real data.
- Generated data, raw data, and local database files must not be committed.
- Do not inspect raw market data, local DuckDB/SQLite files, parquet dumps,
  logs, or cache folders unless the user explicitly asks for that artifact.
- If an assumption about Vietnam market fees, tax, VAT, settlement, liquidity,
  lot size, or trading calendar is uncertain, add a TODO and source
  requirement instead of hardcoding it.
