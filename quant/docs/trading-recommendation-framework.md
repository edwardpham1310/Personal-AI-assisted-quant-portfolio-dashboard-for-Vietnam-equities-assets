# Trading Recommendation Framework

This project uses explainable research signals. A recommendation is a structured
summary of evidence, not a command to trade.

The current product direction is SSI-first, intraday 5m/15m, and recommend-only.
The AI layer may explain and summarize computed facts, but deterministic
indicator/risk code should own the numeric evidence.

## Recommendation Labels

- `Strong Buy`: multiple trend and momentum conditions align, with acceptable
  volatility.
- `Buy`: positive setup, but not enough confirmation for highest conviction.
- `Hold / Watch`: mixed evidence or no strong edge.
- `Reduce / Avoid`: weak trend, deteriorating momentum, or elevated risk.

## Current Technical Inputs

The dashboard MVP uses existing indicator functions:

- Trend: close vs SMA20, SMA20 vs SMA50, 20-day and 60-day return.
- Momentum: RSI14, recent return profile.
- Volume: volume ratio against 20-day average.
- Volatility: ATR14 as a percentage of close.
- Risk: drawdown from recent peak and data freshness.

For intraday work, the same categories apply to 5-minute and 15-minute bars:

- Intraday trend: price vs short/medium moving averages on 5m/15m.
- Intraday momentum: RSI or return acceleration on 5m/15m.
- Intraday volume: volume ratio against same-time/session rolling baselines when
  available.
- Intraday risk: ATR percent, gap risk, liquidity, and portfolio concentration.

## Scoring Philosophy

The score should be transparent and easy to audit:

- Positive trend adds confidence.
- Healthy momentum adds confidence.
- Extreme RSI reduces confidence unless framed as a watchlist bounce setup.
- Volume confirmation helps only when price action agrees.
- High ATR percent or deep drawdown reduces confidence.
- Missing or stale data lowers confidence.

The score is intentionally simple. It is a starting point for discussion and
should later be validated against historical outcomes.

## Recommendation Output

Each recommendation should include:

- Label.
- Numeric score.
- Confidence level.
- Main reasons.
- Risk notes.
- Latest close, RSI, moving averages, volume ratio, ATR percent.
- Data timestamp and timeframe.
- Whether the suggestion is portfolio risk, watchlist entry, add, reduce, exit,
  or rotate candidate.
- AI narrative provenance when Claude/MCP generated the text.

## Guardrails

- Never claim guaranteed profit.
- Never recommend position size without a risk model.
- Avoid recommending illiquid symbols until liquidity filters exist.
- Flag stale data.
- Flag missing fundamentals when discussing long-term investment quality.
- Keep backtest evidence separate from current signal evidence.
- Do not send orders in phase 1. Recommendations are display-only.
- AI must not invent values; it should cite fields read from the database or MCP
  response.

## Future Inputs

Inspired by the `vnstock-agent` reference repo, future versions can add:

- Company overview and sector classification.
- Financial statements and valuation ratios.
- Shareholder and officer data.
- News and events.
- Intraday and price-board data.
- VN30 and exchange-level ranking views.
- SSI read-only account state, then paper trading, then manual approval trading.
