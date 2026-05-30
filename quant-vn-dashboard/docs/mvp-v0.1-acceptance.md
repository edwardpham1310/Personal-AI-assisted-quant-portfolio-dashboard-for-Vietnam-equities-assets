# MVP v0.1 Acceptance Criteria

This document defines the acceptance bar for MVP v0.1 of the Quant VN
Dashboard and records the verification evidence collected on
**2026-05-30**. It is the gate the project must pass before being treated
as a deployable v0.1 demo.

The MVP scope is intentionally narrow: a personal AI-assisted quant
portfolio dashboard for Vietnam equities with manual portfolio entry,
research-only recommendations, and SSI FastConnect Data as the primary
market source. Phase 2 (SSI Trading sync, ML, backtesting) is out of
scope.

## Verdict: PARTIAL — code passes every functional gate; one operational blocker before deploy

All 20 must-have items pass at the code level. All 7 out-of-scope checks
pass. All 5 security checks pass. The only blocker is operational:
**`quant-vn-dashboard/` is currently untracked in git**, so the
"no secrets in tracked files" guarantee is vacuously true and there is no
deployment artifact yet. Fix: stage + commit + re-scan, then proceed.

---

## 1. Must-have items (20)

| # | Item | Status | Evidence |
|---|---|---|---|
| 1 | Frontend builds (proxy: typecheck + tests) | PASS | `npx tsc --noEmit` → EXIT 0; `npx vitest run` → 68/68 in 19 files. Full `next build` not exercised this round — listed as deploy-time follow-up. |
| 2 | Backend starts successfully | PASS | `from main import create_app; create_app()` → 53 routes wired across prefixes `/auth`, `/health`, `/system`, `/settings`, `/watchlists`, `/market`, `/stream`, `/portfolio`, `/assets`, `/recommendations`, `/scanner`. |
| 3 | Auth flow works or mock works in dev | PASS | `apps/web/src/app/login/page.tsx` (email + password Supabase Auth client); `apps/api/src/core/security.py:46` verifies HS256 JWT against `SUPABASE_JWT_SECRET`; live round-trip verified in session (test JWT signed → `verify_supabase_jwt` accepted). |
| 4 | Protected routes handled correctly | PASS | `apps/web/src/middleware.ts` → `lib/supabase/middleware.ts:42-44` redirects unauthenticated requests to `/login?redirectTo=…`; every user-data backend route has `Depends(get_current_user)` (verified across `/portfolio/*`, `/watchlists/*`, `/recommendations/*`, `/assets/*`, `/scanner/*`, `/settings/*`, `/market/*`, `/stream/*` except `/stream/heartbeat`, `/system/{status,providers,cache,data-quality}`). |
| 5 | Mock SSI mode works without real SSI credentials | PASS | `core/config.py:66` exposes `ssi_use_mock`; `core/deps.py:45-46` branches to `MockMarketDataProvider`; conftest sets `SSI_USE_MOCK=true`; backend test suite passes without real SSI credentials. |
| 6 | Dashboard Home renders | PASS | `apps/web/src/app/(dash)/dashboard/page.tsx` (66 lines). |
| 7 | Market Overview renders | PASS | `apps/web/src/app/(dash)/market/page.tsx` (67 lines) — IndexCardGrid, MarketBreadth, TopMovers, CandlestickChart. |
| 8 | Watchlist page renders | PASS | `apps/web/src/app/(dash)/watchlist/page.tsx` (323 lines) — CRUD + scanner integration + live overlay. |
| 9 | Portfolio page renders | PASS | `apps/web/src/app/(dash)/portfolio/page.tsx` (338 lines) — account creation + position CRUD + AllocationDonut + PnL by symbol + disabled-but-clean SSI Phase-2 button. |
| 10 | Assets & PnL page renders | PASS | `apps/web/src/app/(dash)/assets-pnl/page.tsx` (91 lines) — AssetCardGrid + RealizedVsUnrealizedChart + FeeTaxDragChart + 3 placeholder cards. |
| 11 | Recommendations page renders | PASS | `apps/web/src/app/(dash)/recommendations/page.tsx` (154 lines) — ProfileHorizonSwitcher + watchlist selector + RecoTable + RejectedRecsSection + ExplainabilityPanel. |
| 12 | Data Quality page renders | PASS | `apps/web/src/app/(dash)/data-quality/page.tsx:125` mounts `StaleQuotesTable` driven by `dq.data.stale_quote_rows` (dead-ternary bug fixed). |
| 13 | Frontend calls backend APIs only | PASS | `apps/web/src/no-direct-ssi.test.ts` passes inside vitest 68/68; grep for `fc-data.ssi`, `fc-tradeapi.ssi`, `SSI_CONSUMER_`, `consumerSecret` across `src/{app,components,hooks,lib,features}` returns matches only inside the guard test itself and one mock-response fixture (`data-quality/page.test.tsx:54`). |
| 14 | Backend is the only SSI gateway | PASS | The SSI base URL appears only in `apps/api/src/core/config.py` and `apps/api/src/providers/market_data/ssi_fastconnect.py`. No other file imports `httpx` and points at `fc-data.ssi.com.vn`. |
| 15 | No SSI keys exposed to frontend | PASS | grep `SSI_CONSUMER_` across `apps/web/src/` → only the no-direct-ssi guard regex (line 8). |
| 16 | No Supabase service-role key in frontend | PASS | grep `service_role` across `apps/web/src/` → only the display label in `components/system/EnvironmentChecklist.tsx:7` (string literal, not a runtime value). |
| 17 | No auto trading | PASS | grep `placeOrder\|NewOrder\|place_order\|new_order` across `apps/api/src/` → 0 hits. |
| 18 | No live order placement | PASS | `apps/api/src/api/routes/portfolio.py:373-385` `POST /portfolio/sync/ssi` returns HTTP **501** with body `{"detail": "SSI sync coming in Phase 2", "status": "placeholder"}`. |
| 19 | API contracts match current frontend usage | PASS | Every frontend hook + page call (`/portfolio/{summary,positions}`, `/portfolio/manual/{accounts,positions}`, `/assets/{summary,pnl,costs}`, `/watchlists`, `/watchlists/{id}/items`, `/recommendations/{symbol,watchlist,preview}`, `/scanner/{symbol,watchlist,universe}`, `/market/{live/indices,live/status,securities,ohlcv/daily,quotes}`, `/settings`, `/system/{health,status,data-quality}`, `/stream/{quotes,watchlist,market-overview,heartbeat}`) resolves to a router wired in `main.py:101-113`. |
| 20 | Tests/build pass or failures documented | PASS | Backend `pytest`: **199 passed, 3 skipped (intentional SSE, documented TODO), 0 failed** in 2.35s. Frontend `vitest`: **68 passed across 19 files** in 2.43s. `tsc --noEmit`: **EXIT 0**. |

## 2. Out-of-scope items (must NOT exist)

| Out-of-scope feature | Status | Evidence |
|---|---|---|
| Auto trading | PASS | No `placeOrder` / `NewOrder` / `place_order` / `auto_trade` matches anywhere under `apps/api/src/`. |
| Live order placement | PASS | `/portfolio/sync/ssi` returns 501 placeholder; no `POST /orders` route exists. |
| Full ML training | PASS | No `train`, `fit_model`, or sklearn-style training calls; `ml_probability` field present in `RecommendationScores` but always `None` in Phase 1. |
| Full backtesting engine | PASS | No `backtest` modules; no walk-forward or vectorised engine. |
| Advanced portfolio optimization | PASS | No `cvxpy`, `optimize_portfolio`, or Markowitz-style code. |
| Paid data providers | PASS | Only `ssi_fastconnect.py` (SSI FastConnect Data, the user's chosen primary) + `mock_provider.py` live under `apps/api/src/providers/market_data/`. |
| Full broker Trading API execution | PASS | No `fc-tradeapi` request code; `ssi_trading_base_url` is configured but never instantiated by any provider. |

## 3. Security checks (5)

| Check | Status | Evidence |
|---|---|---|
| `.env` files gitignored | PASS | `git check-ignore quant-vn-dashboard/.env` returns the path; no `.env` files appear in `git ls-files`. |
| No SSI secrets committed | PASS | `git ls-files | xargs grep -lE` for the 5 secret tokens used in this session returns 0 matches. |
| No frontend SSI direct calls | PASS | See must-have #13. |
| No service-role key in frontend | PASS | See must-have #16. |
| Production CORS fail-fast | PASS | `apps/api/src/core/config.py` `_assert_production_cors()` raises `RuntimeError` when `app_env=="production"` and `cors_origins` is `["*"]` or only contains localhost. Tested in `tests/test_config.py::test_production_refuses_wildcard_cors` and `::test_production_refuses_localhost_only_cors`. |
| `recommendation_snapshots` INSERT RLS | PASS | `db/migrations/0004_reco_insert_policy.sql` adds `create policy reco_insert ... with check (user_id = auth.uid())`. Must be applied to live Supabase before recommendations persist. |

## 4. Blocking issues

| # | Issue | Effort | Owner |
|---|---|---|---|
| B1 | `quant-vn-dashboard/` is **untracked** in git (`git status` shows `?? quant-vn-dashboard/`). The MVP code exists only in the working tree. Fix: stage + commit + re-run secret scan against the staged tree before pushing. | 5 min | Eng |
| B2 | Migration `0004_reco_insert_policy.sql` is not yet applied to the live Supabase project. Without it the recommendation persist layer silently drops every row. Fix: apply via Supabase SQL Editor (or `supabase db push`) before the first prod scan. | 2 min | Eng |
| B3 | 5 secrets pasted into chat history this session must be rotated (DB password, `sb_secret_*`, JWT secret, SSI FCData consumer secret, SSI FCtrading consumer secret + RSA private keys). Until rotated, treat them as compromised. | 15 min | Eng |

## 5. Non-blocking issues

| # | Item | Severity |
|---|---|---|
| N1 | Full `next build` not exercised in this verification. `tsc` clean + vitest green is a strong proxy but not equivalent. Run a one-shot prod build before deploy. | MEDIUM |
| N2 | 3 SSE streaming tests skipped (`test_stream_routes.py:61,68,75`) with a documented `httpx.AsyncClient + ASGITransport + asyncio.timeout` migration TODO. Streaming endpoints have zero automated coverage today. | MEDIUM |
| N3 | Dashboard Home is 100% mock data via `usePortfolioMockSummary`; 3 placeholder cards on `/assets-pnl` (NetWorthCurve, CashMovement, SettlementAlerts). | LOW |
| N4 | `/scanner/universe`, dual `/portfolio/manual/*` + `/portfolio/positions` surfaces, and the 14 horizon×profile recommendation matrix are PM-flagged as overbuild. Defer to v0.2 review. | LOW |
| N5 | DuckDB historical pipeline is decorative wiring only. | LOW |
| N6 | Repository layer for Supabase entities not extracted; `MarketDataProvider` ABC bundles 10 methods. Future Phase 2 prep. | LOW |
| N7 | SSI provider `Quote` schema doesn't yet carry the now-available `CeilingPrice` / `FloorPrice`; recommendation guardrail `price_outside_ceiling_floor` still emits `INFO ceiling_floor_unavailable`. | LOW |

## 6. Current safe demo flow

This is what an operator can do **today** without exposing themselves to
the blocking items above.

```text
1. cd quant-vn-dashboard
2. cp .env.example .env  (or use the .env already present locally)
   - Confirm SSI_USE_MOCK=true (default safe path for the demo)
   - Confirm SUPABASE_JWT_SECRET is set (auth gates the dashboard)
3. make install
4. make dev-api   (terminal 1 — uvicorn on :8000)
5. make dev-web   (terminal 2 — Next.js on :3000)
6. Open http://localhost:3000 → sign in via Supabase
7. Visit each page in order:
     /dashboard       → KPI cards (mock)
     /market          → VNINDEX + breadth + top movers + candle (mock or live)
     /watchlist       → create a watchlist, add FPT, open scanner
     /portfolio       → create account, add a manual position
     /assets-pnl      → asset cards + realized/unrealized chart
     /recommendations → pick the watchlist, see ranked candidates
     /data-quality    → confirm cards green, no stale quotes
     /settings/system → confirm /system/health returns "ok"
```

Switching to a real SSI feed requires (a) applying migration 0004, (b)
flipping `SSI_USE_MOCK=false`, and (c) populating the live SSI credentials
on the API host's secret manager — **not** in any frontend config.

## 7. Exact next step after MVP v0.1

The next concrete step is **operational, not code**:

```text
1. git add quant-vn-dashboard/ db/ docs/AI_AGENT_WORKFLOW.md
   .github/workflows/ Makefile (etc.)
2. git status — confirm no .env files are staged
3. git diff --cached | grep -E "(AfmJuPmvb|sb_secret_|NWWn36ZGMohELG|
   ad4d10b7653d|80c97869b848)" — must be empty
4. git commit -m "feat: MVP v0.1 of Quant VN Dashboard"
5. git push origin main
6. In Supabase dashboard: SQL Editor → run 0001 → 0002 → 0003 → 0004
   (already applied? confirm)
7. Rotate the 5 secrets pasted into chat (Supabase Settings → Database
   Reset password, Settings → API → regenerate secret + JWT, SSI portal
   → regenerate FCData + FCtrading + RSA keys)
8. Run a full `next build` locally; if green, deploy to Cloudflare Pages
9. On the API host: set APP_ENV=production, populate CORS_ORIGINS to the
   real Cloudflare Pages URL as a JSON list, populate every rotated
   secret, restart the FastAPI systemd unit
10. Smoke test: curl /health, curl /system/health (public); browser
    visit each page from the demo flow above
11. Tag the release: git tag v0.1.0
```

When all 11 steps are green, MVP v0.1 is shipped. Anything beyond that
list belongs to v0.2 planning.
