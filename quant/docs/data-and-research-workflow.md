# Data And Research Workflow

This document defines the normal research loop for agents and humans working on
`quant-vn`.

## Setup

```bash
cd quant-vn
pip install -e ".[dev]"
quant-vn db-init
```

Optional live data support:

```bash
pip install -e ".[dev,vnstock]"
```

If vnstock data requires an API key in the selected provider version, keep it in
`.env` rather than source control.

## Ingest Data

CSV data:

```bash
quant-vn ingest --provider csv --path data/raw/FPT.csv --exchange HOSE
```

vnstock provider:

```bash
quant-vn ingest --provider vnstock --symbol FPT --start 2020-01-01 --end 2025-12-31
```

## Validate Data

```bash
quant-vn validate-data FPT
```

Agents should treat failed OHLCV validation as a blocker for trading
recommendations. Bad price data can create false breakouts, false volatility, and
invalid backtest results.

## Backtest

```bash
quant-vn backtest --strategy ma_cross --symbol FPT --start 2020-01-01 --end 2025-12-31 --html
```

Useful strategies:

- `buy_and_hold`: benchmark only.
- `ma_cross`: trend following.
- `rsi_mean_reversion`: oversold bounce logic.
- `breakout`: momentum breakout with optional volume confirmation.

## Parameter Sweep

```bash
quant-vn sweep --strategy ma_cross --symbol FPT --top-n 10
```

Sweep results are in-sample and must not be treated as production evidence.
Prefer walk-forward validation before trusting optimized parameters.

## Dashboard

```bash
quant-vn dashboard --symbols FPT,HPG,VCB --start 2023-01-01 --end 2025-12-31
```

The dashboard creates a static HTML file in `reports/`. It summarizes price,
trend, momentum, volume, volatility, and a research recommendation.

## Research Hygiene

- Always name the symbol universe and date range.
- State whether data is adjusted or unadjusted.
- Include transaction cost assumptions.
- Separate signal quality from execution feasibility.
- Do not optimize parameters and then claim out-of-sample performance.
- Keep a written note for any manual override or analyst judgment.
