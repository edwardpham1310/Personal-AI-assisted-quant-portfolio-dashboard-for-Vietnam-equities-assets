# Harness Code Governance

Source-of-truth for branch protection, PR workflow, required approvals,
required CI checks, deployment gates, rollback, and emergency-disable
procedure for the Quant VN Dashboard repo.

This document is written in vendor-neutral terms but tested against
Harness Code (the target CI/CD platform). The actual CI implementation
ships as GitHub Actions in `.github/workflows/` — Harness Code can
either import them as steps or run them as gates upstream of a Harness
Pipeline. Either configuration must enforce the rules below.

---

## 1. Repository topology

| Concept | Setting |
|---|---|
| Default branch | `main` |
| Long-lived branches | `main` only (trunk-based) |
| Feature branches | `phase-X.Y-<topic>` or `fix/<issue>` or `chore/<topic>` |
| Direct push to `main` | **Forbidden** |
| Force push to `main` | **Forbidden** |
| Branch deletion of `main` | **Forbidden** |
| Linear history | **Required** (squash-merge only — no merge commits) |

---

## 2. Branch protection (apply on `main`)

These rules must be configured in **both** GitHub UI (Settings → Branches
→ Branch protection rules) **and** Harness Code (Repository Settings →
Branch Rules). The strictest of the two takes effect at merge time.

- ✅ Require a pull request before merging
- ✅ Require approvals: **1** (project is single-operator; raise to 2 once
      a second engineer is onboarded)
- ✅ Dismiss stale approvals when new commits are pushed
- ✅ Require review from Code Owners (see `.github/CODEOWNERS`)
- ✅ Require status checks to pass before merging (list in §5)
- ✅ Require branches to be up to date before merging
- ✅ Require conversation resolution before merging
- ✅ Require signed commits (recommended; enforce once GPG/SSH signing
      is configured on the operator workstation)
- ✅ Require linear history
- ✅ Restrict who can push to matching branches: **no direct pushers**
- ❌ Do not allow force pushes
- ❌ Do not allow deletions
- ✅ Apply rules to administrators (operator must not self-bypass)

---

## 3. Pull-request workflow

1. **Branch from `main`** — name `phase-X.Y-<topic>` for phase work,
   `fix/<topic>` for bug fixes, `chore/<topic>` for tooling/docs.
2. **Implement** following the scope rules in `CLAUDE.md` and
   `AGENTS.md` — minimum-viable diff, no scope creep.
3. **Open a draft PR** as soon as the first commit exists. Use the
   template in `.github/pull_request_template.md`. Fill the
   "Safety surface touched" checklist truthfully — that section drives
   which approvers GitHub auto-requests via CODEOWNERS.
4. **Wait for CI** to go green. The required-checks list in §5 must
   all pass before the PR can be promoted out of draft.
5. **Promote to ready-for-review**. Approvers (see §4) review the
   diff, the safety-surface checklist, and the test plan.
6. **Squash-merge** with a Conventional Commit title:
   `feat(scope): summary`, `fix(scope): summary`, `chore(scope): …`,
   `docs(scope): …`, `refactor(scope): …`, `test(scope): …`.
7. **Delete the branch** after merge.

---

## 4. Required approvals

Approvals are enforced via CODEOWNERS-style mappings. Until the project
has a multi-person team, the single operator (`@edwardpham1310`) serves
all roles, but the **mapping below must still be honored** — meaning
the operator should pause before self-merging a PR touching one of
these areas and ask "would a real Security Engineer / Quant Researcher
sign this off?".

When a second engineer joins, transcribe these mappings into the real
CODEOWNERS file with concrete usernames.

### 4.1 Security Engineer approval REQUIRED for

| Surface | Path patterns |
|---|---|
| Auth / sessions / JWT | `apps/api/src/core/security.py`, `apps/api/src/api/routes/auth*`, `apps/api/src/api/routes/reauth*`, `apps/web/src/lib/supabase*`, `apps/web/src/middleware*` |
| Secrets / env flags | `apps/api/src/core/config.py`, `.env.example`, any `*production*guard*` |
| Cloudflare Worker / BFF SSE proxy | `apps/web/src/app/api/stream/**`, `apps/web/next.config.ts` |
| SSI Trading | `apps/api/src/providers/trading/**`, `apps/api/src/api/routes/trading.py`, `apps/api/src/services/live_orders.py` |
| Auto-trade | `apps/api/src/api/routes/auto_trade.py`, `apps/api/src/services/auto_trade*.py`, `apps/api/src/schemas/auto_trade*.py` |
| Order placement (any path that can submit a real order) | every file in the §5 "trading safety tests" sweep |
| RLS / DB policy | `db/migrations/*.sql` |
| CI workflows / secret-scan rules | `.github/workflows/**`, `.github/gitleaks.toml` |

### 4.2 Quant Researcher approval REQUIRED for

| Surface | Path patterns |
|---|---|
| Recommendation logic | `apps/api/src/services/recommendation*.py`, `apps/api/src/services/scanner*.py`, `quant/src/quant_vn/strategies/**` |
| Order-preview formulas (fees, VAT, sell tax, slippage, lot, ceiling/floor, liquidity) | `apps/api/src/services/order_preview.py`, `apps/api/src/services/paper_execution.py` |
| PnL / equity / drawdown | `apps/api/src/services/paper_performance.py`, `apps/api/src/services/paper_ledger.py`, `apps/api/src/services/portfolio*.py` |
| Auto-trade decision logic (risk validator, scheduler) | `apps/api/src/services/auto_trade_risk.py`, `apps/api/src/services/auto_trade_engine.py`, `apps/api/src/services/auto_trade_scheduler.py` |
| Settlement calendar | `apps/api/src/services/vn_holidays.py` |

A PR touching paths from **both** lists requires **both** approvals
before merge.

---

## 5. Required status checks

All of the following must report **success** on the PR head SHA before
the merge button enables. They map 1:1 to jobs in
`.github/workflows/ci.yml` and `.github/workflows/gitleaks.yml`.

| # | Check | What it proves |
|---|---|---|
| 1 | `CI / Backend (pytest)` | 411+ tests pass; no test newly skipped or removed without justification |
| 2 | `CI / Frontend (tsc + lint + vitest + build)` | `tsc --noEmit` clean; `next lint` exits 0; `vitest run` passes; production-mode `next build` succeeds with `NEXT_PUBLIC_APP_ENV=production` (proves no silent mock-fallback breakage) |
| 3 | `Secret Scan / gitleaks` | No new strings matching the project-specific patterns in `.github/gitleaks.toml` (sb_secret_*, SSI consumer-secret shape, JWT HS256 blob, RSA private key block) |
| 4 | **Backend startup smoke** *(to be added — see §10 gap list)* | `python -c "from main import app; assert len(app.routes) > 0"` succeeds on a production-shaped env |
| 5 | **API contract tests** *(future)* | OpenAPI schema diff vs. last release does not break backward-compatible client expectations |
| 6 | **Auth/RLS tests** | Already covered by backend pytest — the `test_auto_trade_routes.py`, `test_trading_routes.py`, `test_paper_trading.py` files include cross-user IDOR, ownership, and RLS-policy assertions. **Status:** ✅ via check #1 |
| 7 | **Trading safety tests** | Already covered by backend pytest — `test_no_live_order_calls_in_source` + `test_no_live_order_calls_in_frontend` sweep the codebase for direct provider-submit calls; `test_production_refuses_*` enforce config invariants. **Status:** ✅ via check #1 |
| 8 | **Cloudflare deployment smoke** *(post-deploy gate — see §7)* | Production URL responds 200 on `/health` proxy + `/` + a known dashboard route |
| 9 | **Worker build** | **N/A by design** — the architecture uses Next.js BFF on Pages instead of a standalone Worker. See `docs/cloudflare-pages-setup.md`. Document the absence rather than fake a green check. |

**Gaps to close** (tracked in §10):
- Check #4 (backend startup smoke) — small follow-up
- Check #5 (API contract tests) — Phase 3
- Check #8 (Cloudflare deploy smoke) — see §7

---

## 6. Merge requirements

| Rule | Enforcement |
|---|---|
| Title follows Conventional Commits | PR template + reviewer eyeball (a real linter is a Phase-3 nice-to-have) |
| All comments resolved | GitHub branch protection |
| All checks green | GitHub branch protection (§5) |
| All CODEOWNERS-required approvals collected | GitHub branch protection (§4) |
| Branch is up-to-date with `main` | GitHub branch protection |
| Squash merge only | GitHub repo setting → "Allow squash merging" only |
| Delete head branch after merge | GitHub repo setting → "Automatically delete head branches" |

---

## 7. Deployment gates

The dashboard ships in three layers. Each layer has its own promotion
gate; **no layer may promote until the previous one has been live in
staging for ≥30 minutes without alerts**.

```
┌────────────────────────┐   merge to main
│  PR merged             │ ──────────────────►  Cloudflare Pages
└────────────────────────┘                      auto-builds preview
            │
            ▼  manual promote to Pages → production
┌────────────────────────┐
│  Frontend on Pages     │ ──────────────────►  Backend deploy gate
└────────────────────────┘                      (Fly.io / GCP run)
            │
            ▼  backend running ≥30 min, no errors
┌────────────────────────┐
│  Backend live          │ ──────────────────►  Worker (N/A — BFF in Pages)
└────────────────────────┘                      Post-deploy smoke
            │
            ▼  smoke green
┌────────────────────────┐
│  Production stable     │
└────────────────────────┘
```

### 7.1 Frontend gate (Cloudflare Pages)
- Pages preview deploy must succeed for the PR commit before merge
- Production deploy is manual promotion (`wrangler pages deployment promote` or Pages UI)
- Post-deploy: hit `https://<prod-url>/` and the SSE proxy `/api/stream/health` to confirm the BFF is reachable

### 7.2 Backend gate (Fly.io / GCP Cloud Run)
- Production startup must fire all four `_assert_production_*` guards
  without raising:
  - `_assert_production_cors`
  - `_assert_production_ssi_real_mode`
  - `_assert_production_order_placement_disabled`
  - `_assert_production_auto_trade_disabled` (now also enforces
    `AUTO_TRADE_WORKER_SECRET` non-empty when worker enabled)
- `GET /health` and `GET /system/status` must respond 200
- `GET /system/status.missing_secrets` must be `[]`
- Roll the backend behind a feature-flag freeze: `auto_trade_live_enabled`
  and `trading_live_order_enabled` stay `false` for the first deploy

### 7.3 Cloudflare deployment smoke (post-deploy)
- Call `https://<pages-url>/` → expect 200
- Call `https://<pages-url>/api/stream/market/live` first chunk arrives
  within 5 seconds
- Call `https://<api-host>/health` → expect 200 with body
  `{"status": "ok"}`
- Call `https://<api-host>/system/status` (authenticated) → expect 200
  with `missing_secrets: []` and `redis_configured: true`

---

## 8. Rollback plan

### 8.1 Frontend rollback (Pages)
1. In Cloudflare Pages dashboard → Deployments → find the last known-good
   deployment.
2. Click "Rollback to this deployment".
3. Verify `https://<pages-url>/` serves the previous bundle (Network
   tab: check `_next/static/.../<hash>` matches the rollback target).
4. If the rollback is blocked, **deploy from `main` at the last-known-good
   SHA**: check out the SHA, push to a `hotfix/rollback-<sha>` branch,
   open a PR, expedite review, merge.

### 8.2 Backend rollback (Fly.io / Cloud Run)
1. `flyctl releases list -a <app>` to see prior versions.
2. `flyctl releases rollback <version> -a <app>` to revert.
3. Hit `GET /health` to confirm the rolled-back image is live.
4. **If the rollback re-introduces a known security issue**, do not
   roll back — flip the kill switch instead (§9).

### 8.3 DB migration rollback
- DB migrations live in `db/migrations/*.sql` and are sequentially
  numbered. **Migrations are forward-only** — no automatic `DOWN`
  scripts. Rollback requires an explicit hand-written reverse migration.
- If a migration breaks production, the recovery path is:
  1. Roll back the backend image to the last release that ran against
     the pre-migration schema.
  2. Write a reverse migration as the next sequential file.
  3. Re-deploy the backend that matches the new (reversed) schema.

---

## 9. Emergency disable trading process

When something is wrong with live or auto trading and the operator
needs to stop **everything** within 60 seconds.

### 9.1 Tier-1: flip the kill switch (sub-minute)

Hit the emergency-stop route as the authenticated operator:

```bash
curl -X POST "https://<api-host>/auto-trade/emergency-stop" \
     -H "Authorization: Bearer $JWT" \
     -H "Content-Type: application/json" \
     -d '{"reason": "operator initiated", "scope": "all_runs"}'
```

This route, in one transaction:
- Sets `auto_trade_state.emergency_stopped_at = now()`
- Flips `auto_trade_settings.mode = "OFF"` for every active run
- Writes `AUTO_TRADE_EMERGENCY_STOP` to the audit log
- Returns HTTP 200 with a confirmation envelope

**After this fires:**
- The auto-trade engine refuses every candidate with rule #2
  `KILL_SWITCH_ACTIVE` → `SKIPPED_KILL_SWITCH`
- The worker tick endpoint, even if called by a valid worker secret,
  finds no active runs to dispatch against

### 9.2 Tier-2: env-level disable (sub-5-minute)

If the kill switch route is itself broken, set these env vars on the
backend host and restart:

```bash
AUTO_TRADE_LIVE_ENABLED=false
AUTO_TRADE_ORDER_PLACEMENT_ENABLED=false
AUTO_TRADE_WORKER_ENABLED=false
AUTO_TRADE_DRY_RUN=true
TRADING_LIVE_ORDER_ENABLED=false
TRADING_ORDER_PLACEMENT_DRY_RUN=true
SSI_TRADING_READ_ONLY=true
```

The production startup guards (`_assert_production_auto_trade_disabled`,
`_assert_production_order_placement_disabled`) will refuse to boot in
any state where these flags are inconsistent — a misconfiguration
fails closed.

### 9.3 Tier-3: block the API at the edge (sub-15-minute)

If the backend itself is rogue and cannot be trusted to honour env
flags, block its public URL at the Cloudflare edge:
1. Cloudflare dashboard → Security → WAF → custom rule
2. Match: `http.host eq "<api-host>" and http.request.uri.path matches "/trading/.*|/auto-trade/.*"`
3. Action: Block
4. Deploy

The frontend continues to render cached/static views, but no order
path is reachable.

### 9.4 Post-incident
- Open an incident PR with the audit-log excerpt + decision timeline
- Run `git log --since=<incident-start>` and `gh pr list --search "merged:>=<incident-start-date>"` to identify the change set in flight
- File a post-mortem in `docs/incidents/<date>-<slug>.md`

---

## 10. Gap list (governance items still to close)

| # | Item | Owner | Target |
|---|---|---|---|
| G1 | Backend startup smoke check in CI (boots `app.routes > 0` against a production-shaped env) | DevOps | Next CI pass |
| G2 | API contract tests (OpenAPI diff vs. last release) | Backend | Phase 3 |
| G3 | Cloudflare post-deploy smoke probe (HTTP + SSE first-chunk) | DevOps | Next deploy |
| G4 | Real CODEOWNERS with multiple usernames | Operator | When second engineer joins |
| G5 | Signed commits (GPG/SSH) enforced | Operator | This quarter |
| G6 | Commit-title linter (Conventional Commits) | DevOps | Phase 3 |
| G7 | Incident template + first dry-run | Operator | Before LIVE_AUTO enabled |
