# MVP v0.1 — Demo Guide

This is the operator's hands-on guide to running the **MVP v0.1 demo** of
the Quant VN Dashboard locally with mock data. It is the companion to
[`mvp-v0.1-acceptance.md`](./mvp-v0.1-acceptance.md) (which is the formal
gate) and to [`deployment.md`](./deployment.md) (which is how the same
build goes to production).

The demo intentionally runs in **mock mode** — no real SSI credentials,
no real Supabase data writes, no orders placed, no money at risk.

## How to run locally

```bash
# 1. From the workspace root (Quant_Finance/):
cd quant-vn-dashboard

# 2. Copy the example env. Mock defaults are safe for the demo.
cp .env.example .env
# Edit ONLY: NEXT_PUBLIC_SUPABASE_URL + ANON_KEY + SUPABASE_JWT_SECRET
# (login won't work without these — see "Required env vars" below)

# 3. Install both apps (Python + Node).
make install

# 4. Run the API and the web app in two terminals.
make dev-api      # terminal 1 → http://localhost:8000 (FastAPI + /docs)
make dev-web      # terminal 2 → http://localhost:3000 (Next.js)

# 5. Open http://localhost:3000 in your browser.
```

If `make install` fails on the Python side, run
`cd apps/api && pip3 install -e ".[dev]"` directly to see the pip error.

## Required env vars (minimum for a working demo)

| Variable | Why it's needed for the demo |
|---|---|
| `NEXT_PUBLIC_API_BASE_URL=http://localhost:8000` | Default in `.env.example`; the browser hits this to reach the API |
| `NEXT_PUBLIC_SUPABASE_URL` | Supabase Auth client uses this — login won't work without it |
| `NEXT_PUBLIC_SUPABASE_ANON_KEY` | Same — frontend session cookies |
| `SUPABASE_URL` | Server-side equivalent (RLS-aware data calls) |
| `SUPABASE_ANON_KEY` | Server-side anon key for PostgREST |
| `SUPABASE_JWT_SECRET` | **Required** — the backend rejects all auth-gated requests with 503 if this is unset |
| `CORS_ORIGINS=["http://localhost:3000"]` | JSON list — comma-separated will NOT parse |
| `SSI_USE_MOCK=true` | **Safe demo default.** Leaves SSI credentials irrelevant |
| `APP_ENV=development` | Lets the API boot with placeholder secrets and only WARN about missing ones |

Everything else (`SSI_CONSUMER_*`, `REDIS_URL`, `UPSTASH_*`, `DUCKDB_PATH`,
poller config, Phase-2 trading placeholders) can stay blank for the demo.
The full reference is in
[`environment-variables.md`](./environment-variables.md).

## Mock mode instructions

- **SSI mock**: `SSI_USE_MOCK=true` swaps in `MockMarketDataProvider`.
  Securities (FPT, MWG, HPG, VNM), indices (VNINDEX, VN30), daily OHLCV
  bars (deterministic, weekday-only), and intraday quotes are all
  generated locally with seeded RNG. No outbound HTTPS to SSI.
- **Redis fallback**: `REDIS_URL` blank → in-memory cache (`name=memory`).
  All cache keys (`quote:{sym}`, `index:{code}`, `market:breadth`, etc.)
  still work; just lost on restart.
- **Market poller off**: `ENABLE_MARKET_POLLER=false`. Quotes are served
  from cache on demand; nothing hammers SSI in the background.
- **Phase-2 SSI Trading**: placeholders exist in env and `Settings` but
  no provider is instantiated. Verified by
  `test_ssi_trading_keys_are_inert_in_phase_1`.

## Demo flow (20 steps)

Tick each item off in order. Every step has been pre-verified at the
code/test layer; this checklist confirms the end-to-end browser experience.

| # | Step | Pass criterion |
|---|---|---|
| 1 | Start backend in mock mode | `make dev-api` → "Uvicorn running on http://0.0.0.0:8000"; visit `http://localhost:8000/docs` → OpenAPI schema renders |
| 2 | Start frontend | `make dev-web` → "Ready in Xs"; `http://localhost:3000` loads without 5xx |
| 3 | Login via Supabase Auth | `/login` form, sign up or sign in with email+password; redirected to `/dashboard?redirectTo=...` cleared |
| 4 | Open `/dashboard` | KPI cards render (Total Equity, Net PnL, Today PnL, Available Cash, Risk Score, Market Regime — mock values OK) |
| 5 | Open `/market` | VNINDEX + VN30 index cards, market breadth, top movers, candlestick chart all render |
| 6 | Open `/watchlist` | "Create a new watchlist" form visible; existing watchlists listed if any |
| 7 | Add symbols FPT, MWG, HPG | each symbol appears as a row after submission; remove button works |
| 8 | See mock/live quotes | quotes column populates within ~5s of subscription; "Stale" badge stays grey |
| 9 | Open `/portfolio` | "Create an account" form visible; existing accounts + positions list |
| 10 | Add manual position | open "Add position" → fill Symbol=FPT, Qty=100, Avg cost=70000 → row appears in table |
| 11 | See portfolio valuation | Market price + Market value + Unrealized PnL columns populate (or `—` with `quote_missing` warning if no quote cached) |
| 12 | Open `/assets-pnl` | 8 KPI cards render (Settled, Pending, Advanced, Cash advance, Stock MV, Total equity, Buying power, Withdrawable) |
| 13 | See asset/PnL summary | Realized vs Unrealized chart + Fee/Tax drag chart render; placeholder cards for Net worth curve / Cash movement / Settlement alerts are clearly labelled |
| 14 | Open `/recommendations` | Profile + horizon switcher visible; pick a watchlist → table populates |
| 15 | See research-only recommendations | every row carries action badge with `aria-label "… — research signal, not financial advice"` + visible "research signal · not advice" subscript; ExplainabilityPanel populates on row click |
| 16 | Open `/data-quality` | Provider / Cache / Supabase / DuckDB / Poller cards render; stale-quote table + failed-symbol table render |
| 17 | See system/provider/cache status | Provider mock=true, Cache name=memory, Poller running=false (default off), Supabase configured=true with `url_host` ONLY (no full URL) |
| 18 | Confirm no frontend direct SSI calls | DevTools → Network → filter `ssi.com.vn` → **zero** matches |
| 19 | Confirm no secrets exposed | DevTools → Network → spot-check any XHR response body → no `sb_secret_…`, no JWT-shape blob in plain text outside Authorization header, no SSI consumer secret |
| 20 | Confirm no order placement exists | `curl -i -X POST http://localhost:8000/portfolio/sync/ssi -H "Authorization: Bearer <jwt>"` returns **HTTP 501** with body `{"detail": "SSI sync coming in Phase 2", "status": "placeholder"}` |

All 20 are backed by automated tests in `apps/api/tests/` and
`apps/web/src/**/*.test.*` — the browser walk-through is the operator's
acceptance pass.

## Known limitations

All documented across prior reports; none block the demo.

| Area | Limitation |
|---|---|
| Dashboard Home | 100% mock data (`usePortfolioMockSummary`); KPI cards render but don't reflect real portfolio yet |
| `/assets-pnl` | 3 placeholder cards (NetWorthCurve, CashMovement, SettlementAlerts) — historical snapshot tables are Phase 2 |
| `/scanner/universe` | Overbuilt for a personal dashboard (PM-flagged); usable but defer to v0.2 review |
| Recommendation matrix | 14 horizon × 2 profile combinations are not backtest-validated; thresholds are heuristic |
| ML probability | Always `None` in Phase 1; weight contributes 0 to final_score (UI shows "Phase 2" badge) |
| Ceiling / floor | SSI DailyStockPrice returns these fields but the recommendation guardrail still emits `INFO ceiling_floor_unavailable` |
| SSE streaming tests | 3 streaming-body tests SKIPPED with documented `httpx.AsyncClient + ASGITransport + asyncio.timeout` migration TODO |
| DuckDB | Decorative health summary only; no historical read/write pipeline yet |
| Dual portfolio surface | Both `/portfolio/manual/*` and `/portfolio/positions` exist; pick one before v0.2 |
| Realized PnL | Gross of fees in Phase 1 (documented simplification) |
| Repository layer | Routes call `db.select` directly; no `repositories/` extraction yet |
| Operator action | 5 secrets pasted in this session's chat history must be rotated before going live |

## Test gate summary (current HEAD)

| Suite | Result |
|---|---|
| `pytest --tb=line -q` (backend full) | **212 passed / 3 skipped (intentional SSE) / 0 failed** in 2.44s |
| `vitest run` (frontend full) | **68 / 68 pass across 19 files** in 2.64s |
| `tsc --noEmit` | **EXIT 0** |
| FastAPI app boot with NO credentials (mock mode) | **53 routes wired**, no exception |
| `.env` gitignored + secret leak scan | **clean** (0 hits for any session-leaked token in tracked files) |
| `no-direct-ssi.test.ts` guard | passing |
| 4 safety regression sweeps (forbidden scanner language, forbidden recommendation language, inert SSI Trading keys, no hardcoded secrets in source) | all passing |

## Recommended next phase (post v0.1 demo)

In priority order based on user value vs. implementation cost:

1. **SSI real data** — flip `SSI_USE_MOCK=false` in production after applying
   migration `0004_reco_insert_policy.sql` and rotating the chat-leaked
   secrets. All provider code is live-verified (token, DailyOhlc, IndexList,
   IndexComponents, DailyStockPrice). Effort: ~30 min operational.
2. **Portfolio sync read-only** — wire `/portfolio/sync/ssi` to pull
   SSI Trading **balances + positions only** (no order placement, no
   write API). Phase 2 placeholders in env are already inert-tested.
   Effort: ~1 dev-day; gated by an explicit feature flag.
3. **Better scanner** — wire SSI `CeilingPrice` / `FloorPrice` into
   `Quote` schema + recommendation guardrail (currently emits INFO
   `ceiling_floor_unavailable`). Add multi-timeframe confirmation
   (daily + 15m). Effort: ~2-3 dev-days.
4. **Backtest module** — narrow vectorised engine using existing
   `quant/` workspace, walk-forward validation, log results to
   Supabase. Validates the 14×2 recommendation matrix and lets the
   team prune to a smaller defensible set. Effort: 1–2 weeks.
5. **ML later** — once backtest is producing OOS PnL metrics, train an
   XGBoost overlay on engineered features. `ml_probability` field +
   weight is already wired in the schema; just inject a real value.
   Effort: 2–4 weeks, fully behind a feature flag.

Out-of-scope for the next phase: full auto-trading, broker-driven
execution, advanced portfolio optimization, multi-currency, paid data
providers, dark-pool / off-exchange routing.

## Where to look when something is wrong

| Symptom | First place to look |
|---|---|
| API 5xx on any auth-gated route | `core/security.py` + check `SUPABASE_JWT_SECRET` is set |
| Login redirects in a loop | `apps/web/src/middleware.ts` + `lib/supabase/middleware.ts` |
| `/system/health` returns `degraded` | cache backend can't ping; check `REDIS_URL` / Upstash creds or expect in-memory fallback |
| Scanner returns empty in mock mode | mock provider has only 4 symbols (FPT, MWG, HPG, VNM); add one of those to the watchlist |
| `npx tsc --noEmit` fails | re-read this turn's `mvp-v0.1-acceptance.md` for the 2 typed-route casts that may have regressed if next.js bumped |
| `.env` accidentally tracked | `git rm --cached quant-vn-dashboard/.env` then commit |
| A test fails after a future change | start with `test_no_hardcoded_secrets_in_production_source` and the 3 forbidden-language sweeps — they fail loudly with a clear remediation hint |

Tag `v0.1.0` once the 20-step demo checklist passes in the browser.
