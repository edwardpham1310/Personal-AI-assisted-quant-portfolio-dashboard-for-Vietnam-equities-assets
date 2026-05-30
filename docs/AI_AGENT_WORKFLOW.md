# AI Agent Workflow

This repo is set up for small, targeted AI coding sessions. Claude Code,
Codex, Aider, Continue, and Repomix should operate on source files,
configuration, docs, tests, and tiny fixtures. They should not load runtime
market data, database files, logs, build outputs, or generated context bundles.

## Why 1M Context Is Disabled

Claude Code 1M context can be expensive and can fail with:

```text
API Error: Usage credits required for 1M context
```

This project does not need full-repo or full-data context. Quant work is safer
when agents inspect schemas, interfaces, validation rules, tests, and small
fixtures.

The repo-level Claude configuration sets:

```bash
CLAUDE_CODE_DISABLE_1M_CONTEXT=1
```

You can also set it in your shell:

```bash
export CLAUDE_CODE_DISABLE_1M_CONTEXT=1
claude --model claude-sonnet-4-5
```

## Generate Small Context With Repomix

Use Repomix when an AI review needs compressed repo context:

```bash
npx repomix
```

For narrow reviews, include only the files needed:

```bash
npx repomix --include "src/**/*.py,tests/**/*.py,README.md"
```

The default config writes generated output to:

```text
ai-context/repomix-output.md
```

Generated AI context is ignored by git and should not be committed.

## Files Agents Should Avoid

AI agents must not inspect full raw market data files or database files. They
should work through schema files, sample fixtures, typed interfaces, validation
rules, and small test datasets.

Avoid:

- `data/raw/`
- `data/processed/`
- `data/cache/`
- `data/vendor/`
- `datapipe/data/`
- `quant/data/`
- `db/`
- `ai-context/`
- `.git/`
- `.venv/`, `venv/`, `node_modules/`
- `dist/`, `build/`, `.next/`, `coverage/`
- Large `*.csv` exports; tiny files under `tests/fixtures/` are allowed.
- `*.parquet`, `*.duckdb`, `*.sqlite`, `*.sqlite3`, `*.db`, `*.log`

## Aider And Continue

Use Aider or Continue on specific files rather than the whole repository:

```bash
aider src/path/to/file.py tests/path/to/test_file.py
```

Good prompts:

```text
Edit only quant/src/quant_vn/costs/taxes.py and quant/tests/test_costs_taxes.py.
Do not read data files. Use tests/fixtures if sample rows are needed.
```

```text
Review datapipe/src/quant_vn_data/validation/ohlcv_checks.py for duplicate date
handling. Do not inspect runtime databases or raw provider files.
```

## Data Access Rules

Runtime data is outside normal agent context:

- Real DuckDB/SQLite files must not be committed.
- Large CSV/parquet files must not be committed.
- Raw provider data belongs in `data/raw/` or package runtime data folders.
- Processed datasets belong in `data/processed/`.
- Agents should use `src/data_pipeline/` interfaces and `tests/fixtures/`.
- Storage code should expose functions/classes instead of requiring database
  file inspection.

## Quant-Specific Review Rules

When editing quant logic for Vietnam markets, account for:

- Brokerage fees.
- Tax assumptions.
- VAT/service fees when relevant.
- Slippage.
- Liquidity filters.
- Settlement delay.
- Trading calendar.
- Corporate actions.
- Lot size and order constraints.

If an assumption is uncertain, add a TODO and source requirement instead of
hardcoding it.

## Troubleshooting

If Claude reports:

```text
API Error: Usage credits required for 1M context
```

Run:

```bash
export CLAUDE_CODE_DISABLE_1M_CONTEXT=1
claude --model claude-sonnet-4-5
```

Then restart the Claude Code session from a small prompt with explicit files.
