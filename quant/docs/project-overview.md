# Project Overview

`quant-vn` is a personal quantitative trading research platform for the Vietnam
stock market. It supports local OHLCV data ingestion, quality validation,
indicator calculation, long-only strategy backtesting, research sweeps, and
report generation.

The project direction is a personal AI-assisted quant portfolio dashboard for
Vietnam market assets. It should be treated as a research decision-support
system. It can rank setups, expose risk, and explain why a signal exists, but it
should not present recommendations as financial advice or execute trades
automatically in the first phase.

## Primary Users

- A retail or professional researcher studying Vietnam equities.
- A personal portfolio owner who wants explainable intraday risk alerts and
  trade suggestions.
- An AI agent or analyst that needs reproducible market data, indicators, and
  strategy results.
- A developer extending the research platform with new data providers, signals,
  dashboard views, or backtest capabilities.

## Current Capabilities

- CSV and optional vnstock data ingestion.
- SQLite storage for OHLCV, symbols, corporate actions, backtest runs, trades, and
  equity curves.
- OHLCV cleaning and validation.
- Technical indicators: SMA, EMA, RSI, ATR, Bollinger Bands, OBV, volume ratio,
  volatility, momentum.
- Starter strategies: buy-and-hold, moving average crossover, RSI mean reversion,
  breakout.
- Vectorized single-symbol backtest engine with next-open execution.
- Transaction cost assumptions for Vietnam market: commission, sell tax, and
  slippage.
- CLI workflows for database init, ingestion, validation, backtest, sweeps,
  reports, and symbol discovery.

## Reference Repo Notes

The reference repo `mrgoonie/vnstock-agent` is an MCP/CLI wrapper for Vietnamese
market data via vnstock. Useful ideas for this project:

- Keep data access commands clear and composable.
- Separate provider concerns from analysis concerns.
- Document environment variables and API key requirements.
- Consider future MCP integration when agents need live market tools.

This project should not copy the reference repo architecture directly. `quant-vn`
already has a richer backtest and research structure, so vnstock integration
should remain a provider layer unless an MCP interface becomes a deliberate
roadmap item.

## Product Direction

Near-term direction:

- Add a local web dashboard that reads the existing database and produces
  explainable trading research signals.
- Make SSI the primary integration target for market data and future broker
  workflows.
- Move tactical signals toward intraday 5-minute and 15-minute bars.
- Add Claude/MCP narrative generation from database-backed indicators and
  portfolio state.
- Keep the initial phase recommend-only with no live order placement.
- Expand documentation so multiple agents can collaborate without drifting from
  the same assumptions.
- Improve persistence of backtest runs, dashboard snapshots, and research notes.

Medium-term direction:

- Add fundamentals and valuation data from vnstock-compatible sources.
- Add portfolio-level ranking and watchlist workflows.
- Add walk-forward validation views to reduce overfitting.
- Add MCP tools so Claude can read portfolio state, computed indicators, risk
  alerts, and recommendation evidence from the database.
- Add broker read-only sync before any manual approval trading workflow.
