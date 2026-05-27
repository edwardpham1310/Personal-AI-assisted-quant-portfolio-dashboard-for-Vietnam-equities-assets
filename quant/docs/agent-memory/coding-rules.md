# Coding Rules For Agents

All agents must follow these rules when changing `quant-vn`.

## Core Concept

`quant-vn` is a Vietnam equity research and backtesting platform. It is not an
auto-trading bot and must not present outputs as guaranteed financial advice.

Every code change should support one of these goals:

- Better data quality.
- More reliable strategy research.
- More transparent backtests.
- More explainable research recommendations.
- Better documentation for humans and agents.

## Required Pre-Work

Before coding, read:

- `CLAUDE.md`
- `quant-vn/docs/agent-memory/shared-context.md`
- `quant-vn/docs/trading-recommendation-framework.md` for signal or dashboard work.
- `quant-vn/docs/dashboard/dashboard-spec.md` for dashboard work.

## Engineering Rules

- Preserve the no-lookahead contract: signal at T executes at T+1 open unless
  explicitly marked academic.
- Keep data providers separate from analysis, strategy, and dashboard logic.
- Keep indicators as pure functions where possible.
- Keep recommendation logic explainable: score, reasons, risks, confidence.
- Do not add heavy dependencies without a clear project need.
- Do not hard-code API keys, tokens, account numbers, or private credentials.
- Store secrets in `.env` or user-managed environment variables.
- Prefer small, auditable changes over broad rewrites.
- Add or update tests when changing behavior.
- Do not remove existing risk disclaimers.

## Financial Safety Rules

- Use "research signal", "recommendation label", or "watchlist note".
- Avoid language like guaranteed profit, sure win, risk-free, or must buy.
- Include risk notes when producing trading recommendations.
- Flag stale, missing, or low-coverage data.
- Separate current technical signal evidence from backtest evidence.
- Treat in-sample parameter sweeps as exploratory until walk-forward validation
  exists.

## Audit Notes

Every meaningful code/doc change should add a short audit note under
`quant-vn/docs/audit/`.

Use this filename format:

```text
YYYY-MM-DD-short-change-name.md
```

Use this template:

```markdown
# Audit Note: <short change name>

Date: YYYY-MM-DD
Agent: <agent or human name>

## Intent

Why this change was made.

## Files Changed

- `path/to/file.py`: short reason.

## Behavior Changed

What users or agents can do differently now.

## Verification

- Command run and result.

## Follow-Ups

- Open questions or next steps.
```

## Docs Update Rule

When changing code, update related docs in the same change:

- Dashboard changes: update `quant-vn/docs/dashboard/dashboard-spec.md`.
- Recommendation logic changes: update
  `quant-vn/docs/trading-recommendation-framework.md`.
- Data provider changes: update `quant-vn/docs/data-and-research-workflow.md`.
- Architecture changes: update `quant-vn/docs/system-architecture.md`.
- Agent workflow changes: update files under `quant-vn/docs/agent-memory/`.

If no docs update is needed, state that explicitly in the audit note.

## Completion Checklist

- Concept still matches `quant-vn` research/backtest direction.
- Tests or smoke checks were run.
- Audit note was written.
- Related docs were updated or explicitly marked not needed.
- Any limitations are visible to the user.
