# GitNexus / MCP Notes

How AI coding agents (Codex, Claude Code) should use the GitNexus code
graph instead of full-text searching the repo, and which paths must
never be indexed.

---

## 1. Availability

### 1.1 Workspace state
- ✅ `gitnexus@latest` available via `npx` (no global install required)
- ✅ npm scripts wired in `quant-vn-dashboard/apps/web/package.json`:
  - `npm run gitnexus:analyze` — full reindex (with embeddings)
  - `npm run gitnexus:analyze:fast` — index-only, drop embeddings
    (use this after small refactors)
  - `npm run gitnexus:analyze:force` — full reindex, ignore cache
  - `npm run gitnexus:mcp` — start the MCP server (for Codex
    project-local `.codex/config.toml`)
  - `npm run gitnexus:serve` — start the GitNexus web UI on
    `http://localhost:7777`
- ✅ `.gitnexusignore` at the repo root excludes data, caches,
  build artefacts, and DB dumps (see §3)
- ✅ Project-local MCP config exists at `.codex/config.toml`:
  ```toml
  [mcp_servers.gitnexus]
  command = "npx"
  args = ["-y", "gitnexus@latest", "mcp"]
  ```
- ⚠️ Claude Code reads MCP config from `~/.claude/mcp.json` or per-IDE
  settings, **not** from `.codex/config.toml`. If Claude Code is the
  active agent and you want graph-backed answers, either (a) configure
  the same MCP server in Claude's own settings, or (b) ask Claude Code
  to run `npx gitnexus@latest analyze --index-only --drop-embeddings`
  and consult the resulting graph files in `.gitnexus/` directly.

### 1.2 Last known good index
- `10,338 nodes / 18,915 edges / 334 clusters / 300 flows` (reindexed
  2026-06-01 after VN holiday calendar + production guard landed)

---

## 2. Recommended workflows

### 2.1 Route / service mapping
Before patching a route, ask the graph for everything that calls or is
called by the route handler:

```text
"What modules import services.live_orders.revalidate_for_submit?"
"What functions does api.routes.trading.submit_live_order_intent call?"
"What audit-log action enum values does services.auto_trade_engine emit?"
```

This replaces a `grep -rn "..."` sweep that returns a hundred matches
and forces you to open thirty files.

### 2.2 Impact analysis before patches
Before changing a function signature, ask the graph for the call
fan-out. The answer is the exact set of callers you need to update,
not "all files that mention the name":

```text
"Show the call-chain of services.order_preview.calculate_preview
across the api/routes layer."
"What tests assert on the shape of TradingProviderError.client_safe_message?"
```

### 2.3 Trading call-chain audit
Run this before any merge that touches a trading-safety surface:

```text
"From every POST route under /trading/* and /auto-trade/*,
what is the call chain that ends at TradingProvider.submit_order?"
```

The expected answer is exactly:
- `POST /trading/live-order-intents/{id}/submit` → `services.live_orders.submit_live_order_intent` → `provider.submit_order` (Phase 3 stub today, raises 501)
- `services.auto_trade_engine._dispatch_live_auto` → raw `db.update` walk → `provider.submit_order` (the Phase 2.10 convergence target)

Any **other** path from a route to `submit_order` is a security finding.

### 2.4 Secret usage path audit
Before opening a Cloudflare Pages env-var change PR, confirm no
frontend bundle reads a forbidden env name:

```text
"What files in apps/web/src reference an environment variable name
matching SSI_*_SECRET, SUPABASE_SERVICE_ROLE_KEY, SUPABASE_JWT_SECRET,
UPSTASH_REDIS_REST_TOKEN, REDIS_URL, DATABASE_URL,
SSI_TRADING_CONSUMER_SECRET, or AUTO_TRADE_WORKER_SECRET?"
```

The expected answer is the empty set. Anything in that list appearing
in `apps/web/src` is a leak vector — the build will inline the value
into the client JS bundle.

---

## 3. What MUST be excluded from indexing

Already enforced by `.gitnexusignore` at the repo root. The list:

| Pattern | Why |
|---|---|
| `.git/` | VCS metadata |
| `.gitnexus/`, `.gitnexus-cache/` | GitNexus's own state |
| `node_modules/`, `.next/`, `dist/`, `build/`, `coverage/` | Build/cache output |
| `.venv/`, `venv/`, `__pycache__/`, `.pytest_cache/`, `.mypy_cache/`, `.ruff_cache/`, `.cache/` | Python/tool caches |
| `tmp/`, `logs/` | Ephemeral runtime |
| `ai-context/` | Generated context dumps |
| `data/raw/`, `data/processed/`, `data/cache/`, `data/vendor/` | Raw market data |
| `datapipe/data/`, `quant/data/`, `quant-vn-dashboard/data/` | Per-package data dirs |
| `db/`, `quant-vn-dashboard/db/` | Local DuckDB / SQLite dumps |
| `*.csv` (with allow-list re-include for `tests/fixtures/*.csv`) | CSV exports |

**Do not add to the index:**
- Anything containing real customer or operator data
- DuckDB / SQLite database files (`*.duckdb`, `*.sqlite`, `*.db`)
- Parquet dumps (`*.parquet`)
- Encrypted backups
- Sealed-secret files

If you find one of the above tracked by git, that itself is a finding —
move it out of the repo, not into `.gitnexusignore`.

---

## 4. Cadence

| Trigger | Command |
|---|---|
| After a module-boundary change (new service, new route, moved file) | `npm run gitnexus:analyze:fast` |
| After a dependency-import refactor | `npm run gitnexus:analyze:fast` |
| Weekly or before each release | `npm run gitnexus:analyze` (full, with embeddings) |
| If the graph answers feel stale | `npm run gitnexus:analyze:force` |

The fast variant takes ~10 seconds on this repo; the full variant
takes ~60 seconds. The MCP server is read-only — it does not need a
restart after re-analyze; just refresh the prompt.

---

## 5. Agent prompting hints

When asking GitNexus a question, **be specific about the answer shape
you want**. The graph returns paths, not narrative — formulate
queries that map to graph operations:

| Bad prompt | Good prompt |
|---|---|
| "Tell me about trading" | "List every file in `apps/api/src/services/` that imports `services.order_preview`" |
| "Is the order preview safe?" | "Trace the call chain from `POST /trading/order-preview` to `OrderPreviewResult`. List intermediate function calls in order." |
| "What does the kill switch do?" | "What writes to the column `auto_trade_state.emergency_stopped_at`? What reads it?" |
| "Where are secrets handled?" | "List references to `Settings.*_secret` attributes outside `core/config.py`." |
