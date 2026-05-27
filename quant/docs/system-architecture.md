# System Architecture

`quant-vn` is a Python package organized around a small number of domain layers:
configuration, data, market assumptions, indicators, strategies, backtesting,
research, visualization, and CLI entrypoints.

## Module Map

```text
src/quant_vn/
├── cli.py
├── config/
├── data/
│   ├── providers/
│   ├── cleaning.py
│   ├── ingestion.py
│   ├── models.py
│   ├── storage.py
│   └── validation.py
├── market/
├── indicators/
├── strategies/
├── backtest/
├── research/
├── visualization/
└── dashboard/
```

## Data Flow

1. A provider loads raw OHLCV data.
2. `IngestionPipeline` cleans and validates records.
3. `PriceRepository` writes normalized bars to SQLite.
4. Research code loads OHLCV from `PriceRepository`.
5. Indicators and strategies transform price data into signals.
6. `BacktestEngine` executes signals using configured execution and cost rules.
7. Reports, CSVs, HTML charts, and dashboard snapshots are written to `reports/`.

## Storage

SQLite is the local source of truth for the MVP.

Core tables:

- `price_bars`: normalized OHLCV data.
- `symbols`: symbol metadata.
- `corporate_actions`: dividends, splits, bonus issues.
- `backtest_runs`: strategy run metadata and headline metrics.
- `backtest_trades`: completed trades for a run.
- `backtest_equity_curve`: daily equity, cash, position value, drawdown.

## Backtest Contract

The backtest engine protects against lookahead bias:

- Strategies generate signals from data available through bar T.
- Default execution is next-open: signal at T executes at T+1 open.
- Rolling indicators use full-window warmups.
- Same-close mode should be treated as academic only.

## Dashboard Contract

The dashboard should be a consumer of existing repositories and indicator
functions. It should not duplicate storage logic or mutate research data.

The first dashboard implementation is static HTML:

- Read symbols and OHLCV from SQLite.
- Compute indicators and a transparent signal score.
- Generate an HTML file under `reports/`.
- Keep output reproducible and dependency-light.

## Extension Points

- Data providers: add files under `data/providers`.
- Indicators: add pure functions under `indicators`.
- Strategies: subclass `AbstractStrategy`.
- Research workflows: add parameter or validation tools under `research`.
- Dashboard panels: add analysis transforms and HTML rendering under `dashboard`.
