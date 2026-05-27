# Dashboard Spec

The dashboard is a local web report for analyzing Vietnam stock symbols already
available in the `quant-vn` database.

## Goals

- Serve as the personal AI-assisted quant portfolio dashboard for Vietnam market
  assets.
- Show a concise market snapshot for a watchlist.
- Show current portfolio positions, P/L, allocation, concentration, and risk
  warnings.
- Prioritize intraday 5-minute and 15-minute tactical signals when the data layer
  supports them.
- Explain technical recommendation labels.
- Display Claude/MCP natural-language summaries based on DB-backed indicators
  and portfolio state.
- Link dashboard outputs to the same data, indicators, and cost assumptions used
  elsewhere in the project.
- Keep the first version dependency-light and easy to run from the CLI.

## Non-Goals

- Live auto-trading.
- Live order placement.
- Guaranteed buy/sell advice.
- High-frequency tick execution.

## Confirmed Product Decisions

- SSI-first for market data and future broker integration.
- Core tactical signal timeframes: 5m and 15m.
- AI layer: Claude + MCP reads computed database facts and writes natural-language
  analysis, risk alerts, and buy/sell watchpoints.
- Asset scope: all supported Vietnam market assets over time, not only common
  stocks.
- Initial phase: recommend-only. No real order placement from the dashboard.

## MVP Command

```bash
quant-vn dashboard --symbols FPT,HPG,VCB --start 2023-01-01 --end 2025-12-31
```

Optional arguments:

- `--symbols`: comma-separated symbols. If omitted, use all symbols in database.
- `--start`: analysis start date.
- `--end`: analysis end date.
- `--output`: custom HTML path.

## MVP Panels

- Header: universe, date range, generated timestamp, disclaimer.
- Portfolio: holdings, cash/manual cash placeholder, allocation, P/L, exposure,
  concentration.
- Intraday signals: 5m/15m trend, momentum, volume, volatility, and risk state.
- Recommendation table: symbol, label, score, confidence, close, RSI, SMA20,
  SMA50, volume ratio, ATR percent.
- Reasons and risks: short notes per symbol.
- AI narrative: Claude-generated summary that cites DB facts used as evidence.
- Charts: close, SMA20, SMA50, volume bars for each symbol.

## Broker Integration Roadmap

1. Recommend-only dashboard.
2. SSI read-only account sync if API access is approved.
3. Paper-trading proposed orders.
4. Manual approval order placement with guardrails.
5. Limited automation only after validation and explicit user approval.

## Visual Direction

- Quiet, utilitarian research dashboard.
- Dense but readable tables.
- Avoid marketing-style landing pages.
- Use neutral background, restrained accent colors, and clear status labels.

## Future Dashboard Ideas

- Strategy comparison panel.
- Walk-forward validation panel.
- VN30 ranking heatmap.
- Fundamental quality panel from vnstock-compatible data.
- News/event risk panel.
- Export dashboard snapshot metadata to SQLite.
- SSI order-status view in read-only/manual-approval phases.
