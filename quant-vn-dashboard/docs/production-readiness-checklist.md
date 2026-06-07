# Production Readiness Checklist

Final gate before flipping `auto_trade_live_enabled` or
`trading_live_order_enabled` to `true` in production. Every box must
be ticked, with the verifier's initials + date.

Cross-references:
- Deploy procedure: [`production-runbook.md`](production-runbook.md)
- Governance gates: [`harness-code-governance.md`](harness-code-governance.md)
- Day-to-day ops: [`operations-runbook.md`](operations-runbook.md)
- Demo checklist (V0.1): [`mvp-v0.1-demo.md`](mvp-v0.1-demo.md)
- Acceptance criteria (V0.1): [`mvp-v0.1-acceptance.md`](mvp-v0.1-acceptance.md)

**Phase gate semantics:**
- 🟢 Required before any production deploy (even read-only)
- 🟡 Required before flipping `trading_live_order_enabled=true`
- 🔴 Required before flipping `auto_trade_live_enabled=true`

---

## 1. Public web (Cloudflare Pages)

| | Item | Phase | Verified |
|---|---|---|---|
| ☐ | Pages project linked to GitHub repo, building on push to `main` | 🟢 | |
| ☐ | Production environment vars set per `production-runbook.md` §1.2 | 🟢 | |
| ☐ | `NEXT_PUBLIC_APP_ENV=production` is set (enables `disableMockOnError` default) | 🟢 | |
| ☐ | No `NEXT_PUBLIC_*SECRET*` / `*SERVICE_ROLE*` / `*PRIVATE*` vars exist | 🟢 | |
| ☐ | Custom domain attached, HTTPS-only, HSTS enabled | 🟢 | |
| ☐ | Pages "Always Use HTTPS" rule on | 🟢 | |
| ☐ | Preview deploys are NOT publicly indexed (X-Robots-Tag noindex) | 🟢 | |
| ☐ | Bundle inspection: no `sb_secret_*` / SSI consumer secret / JWT blob in any chunk | 🟢 | |
| ☐ | DevTools Network on production: no forbidden env name reaches the browser | 🟢 | |

## 2. Auth (Supabase)

| | Item | Phase | Verified |
|---|---|---|---|
| ☐ | Supabase project on a stable plan (Free is OK for personal research; Pro for PITR) | 🟢 | |
| ☐ | `SUPABASE_JWT_SECRET` and `SUPABASE_SERVICE_ROLE_KEY` configured on backend host only — never on Pages | 🟢 | |
| ☐ | Anonymous sign-up disabled (Settings → Authentication → Providers) | 🟢 | |
| ☐ | Email confirmation required (or magic link only) | 🟢 | |
| ☐ | JWT `exp` ≤ 60 min; refresh token rotation enabled | 🟢 | |
| ☐ | Password sign-in disabled if you only intend magic links / OAuth | 🟢 | |
| ☐ | `last_reauth_at` column exists on `auto_trade_settings` (Phase 2.6+ migration applied) | 🔴 | |
| ☐ | Re-auth route `POST /auto-trade/reauth` returns 200 with valid JWT (test in browser) | 🔴 | |
| ☐ | Re-auth freshness window enforced (≤300s) — verified via `test_stamp_reauth_*` tests | 🔴 | |

## 3. Cloudflare Worker

| | Item | Phase | Verified |
|---|---|---|---|
| ☐ | N/A — confirmed no `wrangler.toml` exists; the architecture uses Next.js BFF on Cloudflare Pages Edge runtime | 🟢 | |
| ☐ | SSE proxy `apps/web/src/app/api/stream/[...path]/route.ts` deployed with `runtime = "edge"` | 🟢 | |
| ☐ | SSE first-chunk arrives within 5s on production URL | 🟢 | |
| ☐ | If a future Worker is added: `wrangler deploy --dry-run` passes in CI | future | |

## 4. Backend (FastAPI)

| | Item | Phase | Verified |
|---|---|---|---|
| ☐ | Backend host pinned to a single region matching SSI endpoint geography (Singapore / Tokyo / HK preferred) | 🟢 | |
| ☐ | `APP_ENV=production` set on host | 🟢 | |
| ☐ | All four `_assert_production_*` guards pass at boot (logs show no `RuntimeError`) | 🟢 | |
| ☐ | `GET /health` returns 200 `{"status": "ok"}` | 🟢 | |
| ☐ | `GET /system/status` (authenticated): `missing_secrets: []`, `redis_configured: true`, `redis_reachable: true` | 🟢 | |
| ☐ | `CORS_ORIGINS` includes Pages production URL only (no `*`, no preview URLs) | 🟢 | |
| ☐ | Reverse proxy (Fly.io / Cloud Run) enforces TLS 1.2+ | 🟢 | |
| ☐ | Process limits configured: max workers ≤ host RAM / 512MB | 🟢 | |
| ☐ | Structured JSON logs reaching a sink (Better Stack, Datadog, Grafana Cloud) | 🟢 | |
| ☐ | Slow-query alert wired on Postgres ≥ 1s | 🟢 | |

## 5. SSI Data

| | Item | Phase | Verified |
|---|---|---|---|
| ☐ | `SSI_CONSUMER_ID` + `SSI_CONSUMER_SECRET` populated, rotated within last 90 days | 🟢 | |
| ☐ | `SSI_USE_MOCK=false` (production guard refuses any other value) | 🟢 | |
| ☐ | `GET /market/status` returns `ready=true` against real SSI | 🟢 | |
| ☐ | Sample call `GET /market/live/quotes?symbols=FPT,MWG,HPG` returns non-stale quotes during market hours | 🟢 | |
| ☐ | Quote freshness `stale=true` rate < 5% during market hours | 🟢 | |
| ☐ | Redis cache hit rate > 80% during market hours (per `/system/status`) | 🟢 | |
| ☐ | Rate-limit budget: confirmed SSI call rate is within their per-second cap (instrument in logs) | 🟢 | |

## 6. Chart / recommendation

| | Item | Phase | Verified |
|---|---|---|---|
| ☐ | Daily OHLCV chart renders real data on a known symbol (e.g. FPT) | 🟢 | |
| ☐ | `useDailyOhlcv` does not silently fall back to mock in production (Phase 2A — verified by `useAsyncResource.test.ts`) | 🟢 | |
| ☐ | Recommendation table populates from `/recommendation/candidates` against real SSI | 🟢 | |
| ☐ | "View chart" link on recommendation cards opens the symbol detail page without 404 | 🟢 | |
| ☐ | Score breakdown component renders for every candidate (no `null`s in the chart) | 🟢 | |
| ☐ | ML-probability badge appears only when `ml_probability` is non-null (Phase 2 readiness) | 🟢 | |

### 6.1 Recommendations module (Features 2–7)

| | Item | Phase | Verified |
|---|---|---|---|
| ☐ | Migration `0012_reco_reference_price.sql` applied (`reference_price` column on `recommendation_snapshots`) | 🟢 | |
| ☐ | Migration `0013_alerts.sql` applied (`alerts` table + `alerts_owner` RLS + `updated_at` trigger) | 🟢 | |
| ☐ | Top Picks (`/recommendations/top`) + watchlist picks (`/recommendations/watchlist/{id}/picks`) render real data with honest-empty on cold cache (no mock picks) | 🟢 | |
| ☐ | Explain (`/recommendations/explain/{symbol}`) shows weighted contributions; summary uses research-signal language (forbidden-wording scan green) | 🟢 | |
| ☐ | History (`/recommendations/history`) is RLS-scoped, ascending by date, range-filtered | 🟢 | |
| ☐ | Performance (`/recommendations/performance`) is labelled hypothetical ("not an executed trade"); rows without `reference_price`/quote are skipped, not faked | 🟢 | |
| ☐ | Alerts CRUD (`/alerts`, `/watchlists/{id}/alerts`) RLS-scoped; evaluation is read-only and never places an order | 🟢 | |
| ☐ | Portfolio-aware held facts (`is_held`, `held_weight_pct`, concentration warning) surface on `/recommendations/symbol` when a holding exists | 🟢 | |
| ☐ | Safe label vocabulary only (Watch/Actionable/Accumulate/Wait/Avoid/Risky/Take Profit) — no "buy"/"guaranteed"/"sure profit" wording anywhere in the module | 🟢 | |

## 7. Portfolio

| | Item | Phase | Verified |
|---|---|---|---|
| ☐ | `/portfolio` page loads with real data from `/portfolio/summary` | 🟢 | |
| ☐ | `/assets-pnl` aggregates open positions correctly (smoke against paper account) | 🟢 | |
| ☐ | Equity curve renders without crashing on empty / single-point series | 🟢 | |
| ☐ | Drawdown calculation aligns with `paper_performance.compute_snapshot` test fixtures | 🟢 | |
| ☐ | Legacy mock-backed `usePortfolioMockSummary` is the **only** hook with `disableMockOnError: false` in production | 🟢 | |

## 8. Order preview

| | Item | Phase | Verified |
|---|---|---|---|
| ☐ | `POST /trading/order-preview` returns a valid envelope for a known symbol | 🟡 | |
| ☐ | BUY math: brokerage 15bps + VAT 10% on commission + slippage 10bps + lot/ceiling/floor checks | 🟡 | |
| ☐ | SELL math: brokerage 15bps + VAT 10% on commission + sell tax 0.1% + slippage 10bps + sellable-shares check | 🟡 | |
| ☐ | T+2 settlement date returned uses the **shared VN holiday calendar** (`services/vn_holidays.py`) — verified for Tết / 30-4 / 1-5 / 2-9 | 🟡 | |
| ☐ | CASH_ADVANCE_REQUIRED warning fires when shortfall ≤ pending_cash | 🟡 | |
| ☐ | INSUFFICIENT_CASH rejection fires when shortfall > pending_cash | 🟡 | |
| ☐ | Preview persisted to `order_previews` table with full audit | 🟡 | |
| ☐ | Frontend `/trading-preview` shows "Preview only — no real order will be submitted" banner | 🟡 | |
| ☐ | "Submit real order" button is `disabled` and shows tooltip "Live trading not enabled in this phase" | 🟡 | |
| ☐ | Footer renders `is_live_order_submission_enabled=false` when 5-flag gate is closed | 🟡 | |

## 9. Paper trading

| | Item | Phase | Verified |
|---|---|---|---|
| ☐ | Create a paper account: `POST /paper/accounts` → 201 with starting cash | 🟢 | |
| ☐ | Submit a paper BUY → fills via `simulate_fill` → audit `PAPER_ORDER_FILLED` | 🟢 | |
| ☐ | Provider failure mid-fill → rejection `DATA_UNAVAILABLE` (no fake price) | 🟢 | |
| ☐ | T+2 cash settlement: BUY proceeds appear in cash ledger after 2 business days using VN calendar | 🟢 | |
| ☐ | T+2 share settlement: bought shares move from `pending_quantity` → `sellable_quantity` after 2 business days | 🟢 | |
| ☐ | Sell-then-rebuy regression: cannot sell more than truly settled shares (Phase 2.7 review fix) | 🟢 | |
| ☐ | Equity curve appends are throttled to ≥60s (Phase 2.7 review fix) | 🟢 | |
| ☐ | RLS: query another user's paper account → 404 / empty (verified by `test_paper_trading_routes.py`) | 🟢 | |

## 10. Manual confirm (live order intent)

| | Item | Phase | Verified |
|---|---|---|---|
| ☐ | 5-flag env gate computed correctly by `compute_gate_status` | 🟡 | |
| ☐ | `GET /trading/gate` (authenticated) returns the full gate envelope | 🟡 | |
| ☐ | Intent state machine refuses invalid transitions (DB-side trigger) | 🟡 | |
| ☐ | `revalidate_for_submit` re-runs preview math on submit (catches stale data, expired previews, account flag drift) | 🟡 | |
| ☐ | PREVIEW_EXPIRED fires when intent age > `order_preview_max_age_seconds` (60s default) | 🟡 | |
| ☐ | NOT_CONFIRMED route guard returns 409 BEFORE the gauntlet (Phase 2.8 review fix) | 🟡 | |
| ☐ | REAUTH_REQUIRED fires when JWT `iat` and stamped `last_reauth_at` both > 300s old | 🟡 | |
| ☐ | ACCOUNT_NOT_LIVE_ENABLED fires when `trading_accounts.trading_enabled=false` | 🟡 | |
| ☐ | ORDER_VALUE_OVER_LIMIT fires when single-order value > `max_order_value_vnd` | 🟡 | |
| ☐ | Cross-account cancel IDOR closed: cannot cancel another user's intent (verified by tests) | 🟡 | |
| ☐ | Dry-run path returns `SUBMIT_DRY_RUN_OK` with synthetic broker order id | 🟡 | |
| ☐ | Live path stays at provider 501 stub until Phase 3 wires real SSI Trading HTTP | 🟡 | |

## 11. Auto-trade safety

| | Item | Phase | Verified |
|---|---|---|---|
| ☐ | Default mode `OFF`; `auto_trade_default_mode="OFF"` pinned by test | 🔴 | |
| ☐ | `AUTO_TRADE_LIVE_ENABLED=false`, `_ORDER_PLACEMENT_ENABLED=false`, `_DRY_RUN=true`, `_WORKER_ENABLED=false` at first deploy | 🔴 | |
| ☐ | `validate_live_auto_prerequisites` surfaces all 11 reasons when missing (REAUTH_REQUIRED, RISK_ACK_REQUIRED, MAX_*_REQUIRED, ALLOWED_*_REQUIRED) | 🔴 | |
| ☐ | Engine rule matrix in `services/auto_trade_risk.py` enforces all 12 rules + per-order value ceiling | 🔴 | |
| ☐ | Symbol-cooldown enforced (30 min default per `AUTO_TRADE_SYMBOL_COOLDOWN_MINUTES`) | 🔴 | |
| ☐ | Daily order cap enforced (`max_orders_per_day`) | 🔴 | |
| ☐ | Daily gross-value cap enforced (`max_capital_vnd`) | 🔴 | |
| ☐ | Per-account `trading_enabled` flag enforced in LIVE_AUTO branch (Phase 2.9 review fix) | 🔴 | |
| ☐ | `max_runtime_minutes` auto-stops a run with `MAX_RUNTIME_EXCEEDED` audit | 🔴 | |
| ☐ | Adversarial bypass list (`harness-code-governance.md` §9 cross-ref) all return `BLOCKED` | 🔴 | |

## 12. Kill switch

| | Item | Phase | Verified |
|---|---|---|---|
| ☐ | `POST /auto-trade/emergency-stop` returns 200 within 1s | 🔴 | |
| ☐ | After emergency-stop, every subsequent engine candidate surfaces `KILL_SWITCH_ACTIVE` → `SKIPPED_KILL_SWITCH` | 🔴 | |
| ☐ | `auto_trade_state.emergency_stopped_at` row is non-NULL after stop | 🔴 | |
| ☐ | `auto_trade_settings.mode` flips to `OFF` for every account on stop | 🔴 | |
| ☐ | Audit log row `AUTO_TRADE_EMERGENCY_STOP` written unconditionally | 🔴 | |
| ☐ | Resuming after stop requires the operator to explicitly clear `emergency_stopped_at` + re-validate prerequisites | 🔴 | |
| ☐ | Tier-2 env-disable procedure validated in staging (full backend restart with all flags forced off) | 🔴 | |
| ☐ | Tier-3 Cloudflare WAF custom rule template saved to a secure location, ready to deploy | 🔴 | |

## 13. Audit logs

| | Item | Phase | Verified |
|---|---|---|---|
| ☐ | `trading_audit_logs` table exists, RLS-protected, indexed on `(user_id, created_at desc)` | 🟢 | |
| ☐ | `auto_trade_audit_logs` table exists, RLS-protected, indexed | 🔴 | |
| ☐ | `paper_audit_logs` table exists, RLS-protected, indexed | 🟢 | |
| ☐ | `sanitize_audit_reasons` strips human-readable suffix before persisting (Phase 2.5 review) | 🟢 | |
| ☐ | `sanitize_request_payload` strips credentials before persisting | 🟢 | |
| ☐ | Retention policy documented: minimum 90 days for trading + auto-trade | 🔴 | |
| ☐ | Sample query from `production-runbook.md` §8 returns rows for the operator | 🟢 | |

## 14. Secrets

| | Item | Phase | Verified |
|---|---|---|---|
| ☐ | The 5 chat-history-exposed secrets rotated (DB password, `sb_secret_*`, JWT secret, SSI FCData consumer secret, SSI FCtrading consumer secret + RSA private keys) — see `mvp-v0.1-acceptance.md:78` B3 | 🟢 | |
| ☐ | `git ls-files \| grep -E '\\.env($\|\\.)'` returns **only** `.env.example` | 🟢 | |
| ☐ | `.gitignore` covers `.env`, `.env.*`, `*.env.local` (verify lines 2–5) | 🟢 | |
| ☐ | `gitleaks` CI workflow exists at `.github/workflows/gitleaks.yml` and ran green on the latest PR | 🟢 | |
| ☐ | `AUTO_TRADE_WORKER_SECRET` non-empty (≥32 chars) when `AUTO_TRADE_WORKER_ENABLED=true` (boot guard enforces) | 🔴 | |
| ☐ | All secrets stored in Fly.io secrets / Cloud Run Secret Manager (not plain env vars in IaC files) | 🟢 | |
| ☐ | Operator's local `.env` files are encrypted at rest (FileVault / LUKS / BitLocker) | 🟢 | |

## 15. Tests

| | Item | Phase | Verified |
|---|---|---|---|
| ☐ | Backend pytest green on the deploy commit (target: 411+ passed, 3 skipped, 0 failed) | 🟢 | |
| ☐ | Frontend `tsc --noEmit` clean | 🟢 | |
| ☐ | Frontend `next lint` exits 0 (advisory warnings OK) | 🟢 | |
| ☐ | Frontend `vitest run` green (target: 103+ passed) | 🟢 | |
| ☐ | `test_no_live_order_calls_in_source` + `test_no_live_order_calls_in_frontend` green | 🟡 | |
| ☐ | `test_production_refuses_*` config-guard tests green | 🟢 | |
| ☐ | `test_vn_holidays.py` green and calendar covers the next 12 months | 🟢 | |
| ☐ | `test_paper_trading_routes.py` cross-user IDOR tests green | 🟢 | |
| ☐ | `test_auto_trade_routes.py` worker-tick auth tests green | 🔴 | |
| ☐ | Smoke E2E run on staging (manual): login → preview → paper trade → check audit log | 🟡 | |

## 16. Deployment

| | Item | Phase | Verified |
|---|---|---|---|
| ☐ | Branch protection enabled on `main` per `harness-code-governance.md` §2 | 🟢 | |
| ☐ | `.github/workflows/ci.yml` runs on every PR and must pass before merge | 🟢 | |
| ☐ | `.github/workflows/gitleaks.yml` runs on every PR and must pass before merge | 🟢 | |
| ☐ | CODEOWNERS in place + approvals enforced | 🟢 | |
| ☐ | Cloudflare Pages deploy gate validated (preview must be inspected before promote) | 🟢 | |
| ☐ | Backend deploy gate validated (`_assert_production_*` boot checks all pass) | 🟢 | |
| ☐ | Post-deploy smoke validated against `production-runbook.md` §3.4 | 🟢 | |
| ☐ | Rollback procedure validated: rolled back to prior backend release in staging without data loss | 🟢 | |
| ☐ | Emergency stop dry-run completed: tier-1 kill switch flip + tier-2 env disable both verified in staging | 🔴 | |
| ☐ | Backup verified: restored a recent Supabase snapshot to a sandbox project and confirmed audit-log rows persisted | 🟢 | |
| ☐ | Operator can reach incident channel (whichever you use — Slack DM, SMS, signal-cli) within 60s | 🔴 | |

---

## Sign-off

| Phase gate | All boxes ticked? | Operator initials | Date |
|---|---|---|---|
| 🟢 First production deploy (read-only) | | | |
| 🟡 Manual-confirm live orders enabled | | | |
| 🔴 LIVE_AUTO enabled | | | |

A failed box in any column means **do not promote to that phase**.
Address the failure, re-verify, re-sign.
