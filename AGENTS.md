# Agent Instructions

This is a personal AI-assisted quant portfolio dashboard for Vietnam equities
and related assets. Keep agent work small, targeted, and auditable.

## Context Rules

- Use GitNexus MCP/code graph before broad file reads.
- Do not enable Claude 1M context.
- Do not read large data files.
- Do not open DuckDB or SQLite database files.
- Do not inspect parquet dumps, raw CSV exports, logs, caches, build output, or
  generated AI context files.
- Use `tests/fixtures/` for small examples.
- Use `src/data_pipeline` schemas, validation functions, and storage interfaces
  instead of inspecting runtime data.
- Use Repomix only when compressed repo context is needed.
- Prefer small, file-specific edits for Codex, Aider, Continue, and Claude Code.

## Financial Logic Rules

For quant, portfolio, and recommendation logic, always consider:

- Vietnam market fees.
- Tax assumptions.
- VAT/service fees if relevant.
- Slippage.
- Liquidity filters.
- Settlement delay.
- Trading calendar.
- Corporate actions.
- Lot size and order constraints.

If uncertain, add a TODO with the missing source or configuration need instead
of hardcoding financial assumptions.

## Safe Prompt Pattern

Use prompts like:

```text
Edit only <source-file> and <test-file>. Do not read data/raw, data/processed,
db, package data folders, or generated context files. Use tests/fixtures for
sample rows.
```

## GitNexus-first Policy

All agents must:

- Use GitNexus MCP/code graph before broad file reads.
- Ask GitNexus for relevant modules, symbols, dependencies, and call chains.
- Only open files that are directly relevant.
- Prefer small targeted patches.
- Re-run `npm run gitnexus:analyze` from `quant-vn-dashboard/apps/web` or
  `npx gitnexus@latest analyze` after structural changes.
- Never index or read large local market data files unless the task explicitly
  requires it.
- Avoid reading DuckDB/SQLite database files directly.
- Keep token usage low.

### Architecture Agent

Use GitNexus to map modules and dependency boundaries before proposing
architecture changes.

### Backend Agent

Use GitNexus to find FastAPI routes, services, repositories, workers, and data
connectors before editing.

### Data Pipeline Agent

Use GitNexus to locate SSI/VSDC/vnstock ingestion, validation, storage, and
schema files. Do not read raw market data, parquet dumps, or DB files.

### Frontend Agent

Use GitNexus to find dashboard pages, components, chart modules, hooks, and API
clients before editing.

### Quant Strategy Agent

Use GitNexus to locate strategy, backtest, fee/tax/risk, and recommendation
modules. Avoid touching execution or trading modules unless explicitly
requested.

### Trading Safety Agent

Use GitNexus to inspect order preview, permissions, toggle/password gate, audit
log, and guardrails before changes. Do not enable live order placement unless
explicitly requested.

## Claude Code Harness Policy

All agents must follow the Plan -> Work -> Review -> Verify -> Report loop.

Before editing:

- Identify the active phase.
- Read the acceptance criteria.
- Use GitNexus MCP/code graph first.
- Identify impacted files.
- Do not read the full repository.
- Do not inspect raw market data, local DB files, generated files, cache
  folders, or unrelated modules.

During editing:

- Make minimal targeted changes.
- Do not expand scope.
- Do not implement full ML training.
- Do not implement a full backtesting engine unless the current phase
  explicitly asks for it.
- Do not add paid provider integrations.
- Do not redesign unrelated UI.
- Do not enable auto-trading.
- Do not add live order placement unless the exact phase explicitly allows it.

After editing:

- Run relevant tests/lint/typecheck/build.
- Re-run GitNexus analysis only if module structure, routes, services, or major
  imports changed.
- Report changed files and verification results.

Hook and installer policy:

- Do not run external harness installers inside this repo without explicit
  approval.
- Do not add auto-executing hooks unless they are reviewed, local-only, and
  cannot expose secrets or touch trading/data artifacts.
- Prefer local command templates and docs over broad generated harness state.
- If testing an external harness, use a disposable branch or copy first.
