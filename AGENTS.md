# Agent Instructions

This is a personal AI-assisted quant portfolio dashboard for Vietnam equities
and related assets. Keep agent work small, targeted, and auditable.

## Context Rules

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
