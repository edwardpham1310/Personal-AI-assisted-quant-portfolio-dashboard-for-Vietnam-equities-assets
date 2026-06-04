# AI Agent Workflow with GitNexus Code Knowledge Graph

This repository is configured for small, graph-guided AI coding sessions.
Claude Code, Codex, Aider, Continue, and other coding agents should use
GitNexus to query architecture, symbols, call chains, imports, and file
relationships before reading files directly.

## Repository Shape

This is a monorepo:

- `datapipe/`: Python data ingestion, validation, SQLite/DuckDB export.
- `quant/`: Python strategy, backtest, costs, portfolio, recommendations.
- `quant-vn-dashboard/apps/api/`: FastAPI backend.
- `quant-vn-dashboard/apps/web/`: Next.js dashboard.
- `docs/`, `guide/`: workspace documentation.

Package managers in use:

- Python: `pip` / editable installs from `pyproject.toml`.
- Frontend: `npm` from `quant-vn-dashboard/apps/web/package-lock.json`.
- GitNexus: npx-based commands, no global install required.

Node.js 18+ is required for `npx`; Node.js 20+ is recommended because the
frontend uses Next.js 15.

## Purpose

Use GitNexus to reduce token usage and make safer edits:

- Start from graph queries and repository summaries.
- Identify impacted modules, symbols, imports, call chains, and nearby tests.
- Read only the smallest directly connected file set.
- Avoid pasting large files into context.
- Keep runtime data, databases, caches, and generated indexes out of git.

## Setup

From the frontend package, use the package scripts:

```bash
cd quant-vn-dashboard/apps/web
npm run gitnexus:analyze
npm run gitnexus:analyze:fast
npm run gitnexus:analyze:force
npm run gitnexus:mcp
npm run gitnexus:serve
```

From the repository root, use npx directly:

```bash
npx gitnexus@latest analyze
npx gitnexus@latest analyze --index-only --drop-embeddings
npx -y gitnexus@latest mcp
```

GitNexus embeddings are off by default in the current CLI. Use
`--index-only --drop-embeddings` for quick local graph refreshes and CI-like
checks that do not inject generated text into `AGENTS.md` or `CLAUDE.md`.
The package scripts clean generated `.gitnexus/` folders before analysis so a
stale or incompatible local index cannot poison the next run.

## MCP

Codex uses the project-local MCP config in `.codex/config.toml`:

```toml
[mcp_servers.gitnexus]
command = "npx"
args = ["-y", "gitnexus@latest", "mcp"]
```

If a tool does not read project-local Codex config, add the same block to your
user-level config:

```text
~/.codex/config.toml
```

For Cursor or another editor, use the equivalent MCP command:

```json
{
  "mcpServers": {
    "gitnexus": {
      "command": "npx",
      "args": ["-y", "gitnexus@latest", "mcp"]
    }
  }
}
```

Do not overwrite user-global editor config from this repo.

## Daily Workflow

1. Run GitNexus analyze after major refactors:
   `npx gitnexus@latest analyze --index-only --drop-embeddings`.
2. Ask the agent to use GitNexus MCP/context first.
3. Agent identifies impacted modules/files through graph queries.
4. Agent reads only the smallest necessary file set.
5. Agent edits small, targeted changes.
6. Agent runs focused tests/lint/typecheck for the touched package.
7. Re-run analyze if dependency structure changed.

## Token-Saving Policy

Agents must not read the whole repo.

Agents must not paste large files into context.

Agents must start from graph queries and repo summary.

Agents must inspect only upstream/downstream related files.

Agents must avoid:

- `data/raw/`, `data/processed/`, `data/cache/`, `data/vendor/`
- `datapipe/data/`, `quant/data/`, `quant-vn-dashboard/data/`
- `db/`, `quant-vn-dashboard/db/` runtime DB files
- `.gitnexus/`, `.gitnexus-cache/`, `ai-context/`
- `.git/`, `.venv/`, `venv/`, `node_modules/`, `.next/`
- `*.duckdb`, `*.sqlite`, `*.sqlite3`, `*.db`, `*.parquet`, large `*.csv`,
  logs, caches, and build outputs

Tiny fixtures under `tests/fixtures/` are allowed.

## Quant-Specific Module Map

Use GitNexus to locate these module families before editing:

- Backend API: `quant-vn-dashboard/apps/api/src/api/routes/`,
  `core/`, `services/`, `repositories/`.
- SSI data connector:
  `quant-vn-dashboard/apps/api/src/providers/market_data/`,
  `datapipe/src/quant_vn_data/providers/`.
- DuckDB/SQLite pipeline:
  `datapipe/src/quant_vn_data/storage/`, `src/data_pipeline/`.
- Candle chart service:
  frontend chart components and hooks under `quant-vn-dashboard/apps/web/src/`.
- Strategy engine: `quant/src/quant_vn/strategies/`.
- Backtest engine: `quant/src/quant_vn/backtest/`.
- Portfolio module: `quant/src/quant_vn/portfolio/`,
  `quant-vn-dashboard/apps/api/src/api/routes/portfolio.py`.
- Risk/fee/tax module: `quant/src/quant_vn/costs/`,
  `quant/src/quant_vn/execution/rules.py`.
- Order preview/trading safety module: execution, recommendation validator,
  auth, permissions, audit logging, and guardrails.

## Safety Rules

- Do not edit trading execution code without an explicit task.
- Do not enable auto-trading.
- Do not add real order placement.
- Do not use mock data when the task requires SSI real data.
- Never commit secrets, API keys, SSI credentials, tokens, or local DB files.
- Keep generated data/index files ignored.
- Do not read DuckDB/SQLite database files directly.
- If uncertain about market fees, tax, VAT, settlement, lot size, or trading
  calendar assumptions, add a TODO instead of hardcoding.

## Claude 1M Context

Claude Code 1M context is disabled through `.claude/settings.json`:

```bash
CLAUDE_CODE_DISABLE_1M_CONTEXT=1
```

If Claude reports:

```text
API Error: Usage credits required for 1M context
```

Run:

```bash
export CLAUDE_CODE_DISABLE_1M_CONTEXT=1
claude --model claude-sonnet-4-5
```

Then restart from a small prompt with explicit files or GitNexus graph queries.
