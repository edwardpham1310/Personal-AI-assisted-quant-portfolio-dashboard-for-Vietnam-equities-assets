# Shared Agent Context

All agents should use this as the common project memory.

## One-Sentence Concept

`quant-vn` is a local Vietnam equity quant research platform that turns OHLCV
data into validated indicators, backtests, reports, and explainable research
recommendations.

The product direction is a personal AI-assisted quant portfolio dashboard for
Vietnam market assets.

## Key Decisions

- The system is research-first, not execution-first.
- SQLite is the current local source of truth.
- Technical signals are allowed; financial advice language is not.
- The dashboard should read existing repositories and indicators instead of
  building a separate analytics stack.
- SSI is the preferred ecosystem for data and future broker workflows.
- Tactical signal timeframes are 5m and 15m.
- Claude/MCP can generate natural-language analysis only from DB-backed
  indicators, portfolio state, and auditable facts.
- Phase 1 is recommend-only. Do not implement live order placement unless the
  project explicitly moves to a later phase.
- The `vnstock-agent` repo is a reference for data-access ergonomics and possible
  MCP direction, not a replacement architecture.
- Agents must follow `quant-vn/docs/agent-memory/coding-rules.md` when changing
  code or docs.

## Current Constraints

- T+2 settlement is documented but not fully enforced.
- Corporate actions are modeled but not automatically adjusted.
- Fundamentals are not yet integrated into the core recommendation score.
- Liquidity filters are not yet robust enough for production trading decisions.
- Backtests are single-symbol in the current engine.
- Broker trading APIs must start read-only or paper-trading before real order
  placement.

## Suggested Agent Roles

- Data work: `engineering-data-engineer`.
- Backtest correctness: `engineering-code-reviewer`, `testing-qa-engineer`.
- Signal/recommendation logic: `finance-investment-researcher`.
- Dashboard UI: `design-ui-designer`.
- Documentation: `engineering-technical-writer`.

## Audit Discipline

- Meaningful changes should create an audit note in `quant-vn/docs/audit/`.
- Audit notes should state intent, files changed, behavior changed,
  verification, and follow-ups.
- Related docs should be updated in the same change when behavior or project
  concept changes.

## Shared Vocabulary

- Signal: raw indicator condition.
- Recommendation: human-readable research label derived from multiple signals.
- Confidence: quality of evidence, not probability of profit.
- Risk note: reason a setup may fail or should be watched carefully.
- Universe: set of symbols being analyzed.
- AI narrative: natural-language summary generated from stored facts, not a
  substitute for deterministic signal calculation.
