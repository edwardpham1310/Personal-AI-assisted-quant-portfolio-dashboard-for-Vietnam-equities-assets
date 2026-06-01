# Production Runbook

Step-by-step procedures for deploying, rotating secrets, disabling
trading, rolling back, and recovering from third-party outages.

For day-to-day operations (health checks, alert triage) see
[`operations-runbook.md`](operations-runbook.md). For governance and
PR gates see [`harness-code-governance.md`](harness-code-governance.md).
For the per-release checklist see
[`production-readiness-checklist.md`](production-readiness-checklist.md).

All commands assume the operator is on the workstation with:
- `gh` (GitHub CLI) authenticated to the repo
- `flyctl` (Fly.io CLI) authenticated to the backend app — replace
  with `gcloud` if you migrate to Cloud Run
- `wrangler` (Cloudflare CLI) authenticated to the Pages project
- Supabase dashboard access
- SSI iBoard / FastConnect portal access

---

## 1. Deploy frontend (Cloudflare Pages)

Pages is configured for **auto-deploy on push to `main`** with a
**manual promotion** gate to production.

### 1.1 Standard release
1. PR is merged to `main` (governance gate per
   `harness-code-governance.md`)
2. Cloudflare Pages auto-builds a preview deployment
3. Verify preview at `https://<commit-sha>.<project>.pages.dev`:
   - Open homepage, confirm bundle hash matches the PR's commit
   - Open DevTools → Network → confirm no `sb_secret_*` or SSI
     consumer secret appears in any response body
   - Hit `/api/stream/market/live` (SSE proxy) → first chunk must
     arrive within 5s
4. In Cloudflare dashboard → Pages → project → Deployments → click
   "Promote to production" on the verified preview

### 1.2 Required env vars on Pages (Production environment)
Set via Cloudflare dashboard → Pages → Settings → Environment variables:

| Variable | Value | Notes |
|---|---|---|
| `NEXT_PUBLIC_API_BASE_URL` | `https://<api-host>` | URL of the backend |
| `NEXT_PUBLIC_APP_ENV` | `production` | **Required** — gates `disableMockOnError=true` in `useAsyncResource` |
| `NEXT_PUBLIC_SUPABASE_URL` | `https://<project>.supabase.co` | Public by design |
| `NEXT_PUBLIC_SUPABASE_ANON_KEY` | `<anon key>` | Public by design (RLS protects rows) |

**Never set on Pages:** `SUPABASE_SERVICE_ROLE_KEY`, `SUPABASE_JWT_SECRET`,
`SSI_CONSUMER_SECRET`, `SSI_TRADING_CONSUMER_SECRET`,
`UPSTASH_REDIS_REST_TOKEN`, `REDIS_URL`, `DATABASE_URL`,
`AUTO_TRADE_WORKER_SECRET`. These belong on the **backend** host only.

---

## 2. Deploy Cloudflare Worker

**Not applicable by design.** The dashboard uses a Next.js Backend-For-
Frontend (BFF) running on Pages with Node runtime for SSE proxying
(`apps/web/src/app/api/stream/[...path]/route.ts`). There is no
standalone Worker and no `wrangler.toml`.

If a future phase introduces a real Worker (e.g. for the auto-trade
worker tick), add a new section here with the deploy + smoke procedure.

---

## 3. Deploy backend

### 3.1 Pre-deploy
- All §1 governance gates passed
- Confirm `auto_trade_live_enabled=false` and
  `trading_live_order_enabled=false` are still the production defaults
  unless this is the deliberate go-live deploy

### 3.2 Fly.io deploy
```bash
cd quant-vn-dashboard/apps/api
flyctl deploy --image-label "$(git rev-parse --short HEAD)"
```

### 3.3 Backend env vars (set via `flyctl secrets set`)

| Variable | Required | Notes |
|---|---|---|
| `APP_ENV` | yes | Must be `production` to engage all `_assert_production_*` guards |
| `CORS_ORIGINS` | yes | JSON array; must include the Pages URL only |
| `SUPABASE_URL` | yes | Same value as the frontend's `NEXT_PUBLIC_SUPABASE_URL` |
| `SUPABASE_JWT_SECRET` | yes | From Supabase dashboard → Settings → API → JWT secret |
| `SUPABASE_SERVICE_ROLE_KEY` | yes | `sb_secret_*` — service-role key |
| `DATABASE_URL` | yes | Postgres connection string (read-replica acceptable for read-only routes) |
| `REDIS_URL` or `UPSTASH_REDIS_REST_URL`+`UPSTASH_REDIS_REST_TOKEN` | yes in production | Quote cache |
| `SSI_CONSUMER_ID` | yes | FCData (market data) consumer ID |
| `SSI_CONSUMER_SECRET` | yes | FCData consumer secret |
| `SSI_USE_MOCK` | yes | Must be `false` in production (enforced by `_assert_production_ssi_real_mode`) |
| `SSI_TRADING_USE_MOCK` | yes | Must be `true` until Phase 3 lands the real SSI Trading wire |
| `SSI_TRADING_READ_ONLY` | yes | Must be `true` |
| `SSI_TRADING_ORDER_PLACEMENT_ENABLED` | yes | Must be `false` |
| `TRADING_LIVE_ORDER_ENABLED` | yes | Must be `false` for first deploy |
| `TRADING_ORDER_PLACEMENT_DRY_RUN` | yes | Must be `true` for first deploy |
| `AUTO_TRADE_LIVE_ENABLED` | yes | Must be `false` for first deploy |
| `AUTO_TRADE_ORDER_PLACEMENT_ENABLED` | yes | Must be `false` for first deploy |
| `AUTO_TRADE_WORKER_ENABLED` | yes | Must be `false` for first deploy |
| `AUTO_TRADE_WORKER_SECRET` | conditional | **Required (≥32 chars) when worker enabled**. Boot guard refuses empty + enabled. |
| `AUTO_TRADE_DRY_RUN` | yes | Must be `true` for first deploy |

### 3.4 Post-deploy smoke

**Preferred:** run the bundled script. It runs all four release-gate
checks, validates `missing_secrets=[]`, asserts no `source=mock` rows
on the quote endpoint, and exits non-zero on any failure so it can
be wired into a deploy hook.

```bash
API_BASE_URL=https://<api-host> JWT=<paste> \
  scripts/production-smoke.sh
```

Optional flags:
- `SMOKE_SYMBOLS=FPT,MWG,HPG` — override the symbol list
- `SMOKE_STRICT_QUOTES=1` — also fail when any quote is `stale=true`
  (only meaningful during market hours; outside 09:00–15:00 ICT
  every quote will be stale by design)

**Manual fallback** (use if the script can't run on the operator host):

```bash
curl -s "https://<api-host>/health" | jq .             # {"status": "ok"}
curl -s "https://<api-host>/market/status" | jq .      # ready: true
# Authenticated checks need a Supabase JWT:
curl -s -H "Authorization: Bearer $JWT" \
     "https://<api-host>/system/status" | jq .         # missing_secrets: []
curl -s -H "Authorization: Bearer $JWT" \
     "https://<api-host>/market/live/quotes?symbols=FPT,MWG,HPG" | \
     jq '.[] | {symbol, source, price, stale}'         # source: ssi|cache
```

If any returns non-200 or `missing_secrets` is non-empty: **do not
promote**. Roll back per §8.

---

## 4. Rotate SSI keys

SSI uses two separate credentials: FCData (read-only market data) and
FCtrading (order placement, currently stubbed to Phase 3).

### 4.1 FCData rotation
1. Log in to the SSI FastConnect portal
2. Generate a new `Consumer Secret` for the FCData product
3. On the backend host: `flyctl secrets set SSI_CONSUMER_SECRET=<new>`
4. Wait for Fly to roll the app (`flyctl status` shows new release)
5. Smoke: `curl -s https://<api-host>/market/status | jq .ready` → `true`
6. Revoke the old secret in the SSI portal
7. Audit-log entry: write a row in `system_audit_logs` via direct SQL
   with `action="ssi_fcdata_secret_rotated"` + timestamp

### 4.2 FCtrading rotation (Phase 3 only)
Same procedure but for `SSI_TRADING_CONSUMER_SECRET`. Also rotate the
RSA private key:
1. Generate a new key pair locally:
   `openssl genrsa -out ssi_fctrading.pem 2048`
2. Upload the **public** half to SSI's portal
3. On the backend host:
   `flyctl secrets set SSI_TRADING_PRIVATE_KEY="$(cat ssi_fctrading.pem)"`
4. Confirm the signed-request path works against a `read-only` route
   first before re-enabling any submission flag

### 4.3 Rotation cadence
- Every 90 days minimum
- Immediately after any suspected exposure (chat history, screen
  share, lost laptop, etc.)
- The 5 historical secrets documented in
  `docs/mvp-v0.1-acceptance.md:78` were pasted to chat history and
  must be rotated before first production deploy

---

## 5. Disable trading (non-emergency)

When you want to pause trading for a planned reason (market holiday,
testing, fatigue).

```bash
flyctl secrets set \
  TRADING_LIVE_ORDER_ENABLED=false \
  AUTO_TRADE_LIVE_ENABLED=false \
  AUTO_TRADE_ORDER_PLACEMENT_ENABLED=false \
  AUTO_TRADE_DRY_RUN=true
```

Fly auto-restarts the app. Production startup guards refuse any
inconsistent combination — a misconfiguration fails closed.

Verify via `GET /auto-trade/settings` (authenticated): `mode` returns
to `OFF` for every account, and `gate.all_open` returns `false`.

---

## 6. Emergency stop (sub-minute)

See `harness-code-governance.md` §9 for the three-tier procedure.
The fastest path:

```bash
curl -X POST "https://<api-host>/auto-trade/emergency-stop" \
     -H "Authorization: Bearer $JWT" \
     -H "Content-Type: application/json" \
     -d '{"reason": "operator initiated", "scope": "all_runs"}'
```

This is the **first** thing to do in an incident. Diagnosis comes
after. Audit log entry `AUTO_TRADE_EMERGENCY_STOP` is written
unconditionally.

---

## 7. Rollback

See `harness-code-governance.md` §8 for the per-layer procedure.
Quick reference:

| Layer | Command |
|---|---|
| Frontend | Cloudflare Pages dashboard → Deployments → "Rollback to this deployment" |
| Backend | `flyctl releases rollback <version> -a <app>` |
| DB schema | **Forward-only** — write a reverse migration as the next sequential file, redeploy backend |

---

## 8. Check audit logs

Three audit tables. All carry RLS so the operator's JWT only returns
their own rows.

### 8.1 Trading audit log
```sql
SELECT created_at, action, reason, body
FROM trading_audit_logs
WHERE user_id = auth.uid()
ORDER BY created_at DESC
LIMIT 100;
```

Common actions:
- `trading.order_previewed`
- `trading.new_order_attempt_blocked` (501 forbidden route hit)
- `trading.submit_order_attempt_blocked`
- `trading.cancel_order_attempt_blocked`
- `LIVE_ORDER_INTENT_CREATED` → … → `LIVE_ORDER_SUBMIT_DRY_RUN_OK`
  (or `_LIVE_OK` / `_BROKER_ERROR`)

### 8.2 Auto-trade audit log
```sql
SELECT created_at, action, reason, body
FROM auto_trade_audit_logs
WHERE user_id = auth.uid()
ORDER BY created_at DESC
LIMIT 100;
```

Common actions:
- `AUTO_TRADE_RUN_STARTED` / `_STOPPED` / `_PAUSED` / `_FAILED`
- `AUTO_TRADE_DECISION_MADE` / `_RISK_REJECTED`
- `AUTO_TRADE_WORKER_TICK` / `_WORKER_TICK_BLOCKED`
- `AUTO_TRADE_EMERGENCY_STOP`
- `AUTO_TRADE_REAUTH_SUCCESS` / `_REAUTH_FAILED`

### 8.3 Paper-trading audit log
```sql
SELECT created_at, action, body
FROM paper_audit_logs
WHERE user_id = auth.uid()
ORDER BY created_at DESC
LIMIT 100;
```

Common actions: `PAPER_ACCOUNT_CREATED`, `PAPER_ORDER_FILLED`,
`PAPER_ORDER_REJECTED`, `PAPER_SETTLEMENT_APPLIED`,
`PAPER_RECOMMENDATION_RUN`.

### 8.4 Forensic queries
```sql
-- All blocked submission attempts in last 24h:
SELECT created_at, action, reason
FROM trading_audit_logs
WHERE created_at > now() - interval '24 hours'
  AND action LIKE '%_attempt_blocked'
ORDER BY created_at DESC;

-- All auto-trade decisions today:
SELECT created_at, action, body->>'symbol' AS symbol,
       body->>'rejection_reasons' AS reasons
FROM auto_trade_audit_logs
WHERE created_at >= current_date
  AND action IN ('AUTO_TRADE_DECISION_MADE', 'AUTO_TRADE_RISK_REJECTED')
ORDER BY created_at DESC;
```

---

## 9. Handle third-party outages

### 9.1 SSI down (market data unavailable)

**Symptoms:**
- `GET /market/status` returns `ready=false`
- Quote endpoints return cached data with `stale=true`
- New paper orders reject with `DATA_UNAVAILABLE`
- Auto-trade engine surfaces `SKIPPED_DATA_STALE` for every candidate

**Procedure:**
1. Confirm via SSI status page that it's their outage, not ours
   (`curl -v https://fc-data.ssi.com.vn/...` should fail similarly)
2. **No code change needed** — the safety surfaces are designed for
   this: paper trading refuses to fill, manual-confirm rejects
   submit-time gauntlet, auto-trade engine skips
3. Surface a banner in the dashboard: `useDataQualityStatus` already
   detects this (`isMock=true && error set` in production mode after
   the Phase 2A fix)
4. If outage > 30 minutes, post-incident: write a `docs/incidents/`
   note recording the duration and any paper-order rejections

**Do not:**
- Flip `SSI_USE_MOCK=true` in production to "keep things running" —
  that violates Phase 2A and the production guard
  `_assert_production_ssi_real_mode` will refuse the restart anyway

### 9.2 Redis down (quote cache unavailable)

**Symptoms:**
- `GET /system/status.redis_configured` still `true` but
  `redis_reachable` flips `false`
- Every quote read hits SSI directly → latency spikes 5×
- Rate-limit risk against SSI's per-second cap

**Procedure:**
1. Confirm Upstash (or self-hosted Redis) status
2. **Short outage (<10 min):** ride it out. Backend falls through to
   direct SSI calls.
3. **Long outage:** consider lowering `MARKET_POLL_INTERVAL_SECONDS`
   ceiling temporarily to reduce per-second SSI calls.
4. Once Redis is back: no code action — the cache repopulates lazily.

**Do not:**
- Restart the backend just to "reconnect Redis" — the client
  reconnects automatically.

### 9.3 Supabase down (auth + DB unavailable)

**Symptoms:**
- Every authenticated route returns 401 or 503
- `GET /system/status` returns 503

**Procedure:**
1. Confirm via Supabase status page
2. **Auth-only outage:** users can't log in but in-flight JWTs remain
   valid until their `exp` (default 1h). Existing sessions degrade
   slowly.
3. **DB outage:** the backend cannot read RLS-gated tables. Hit the
   kill switch (§6) to ensure no auto-trade decisions fire on stale
   in-process state.
4. **Long outage:** consider failing over to a read-replica if one is
   configured.
5. When Supabase recovers: no code action. The connection pool
   reconnects.

**Do not:**
- Bypass RLS by switching to the service-role key for read paths —
  that's a security regression dressed up as a fix.

---

## 10. Backup procedure

### 10.1 What needs backing up
| Data | Source | Frequency | Retention |
|---|---|---|---|
| Supabase Postgres (all tables) | Supabase scheduled backup | Daily | 7 days (Free tier) / 30 days (Pro) |
| Source code | GitHub (`origin/main`) | Per push | Forever |
| Cloudflare Pages build artifacts | Cloudflare retains last 100 deployments | Per build | ~100 deploys |
| Audit logs | Postgres (covered by Supabase backup) | — | — |

### 10.2 What does NOT need backing up
- Redis cache (lossy by design — repopulates from SSI)
- Local DuckDB / SQLite files (development only)
- `.next/` build cache (regenerated per build)

### 10.3 Pre-go-live backup checklist
- Enable Supabase Point-in-Time Recovery (PITR) if on Pro plan
- Test restore: spin up a sandbox Supabase project, restore the most
  recent backup, confirm `auto_trade_audit_logs` rows are present
- Document the operator's recovery RPO (recovery point objective) and
  RTO (recovery time objective) — for this dashboard, RPO ≤ 24h and
  RTO ≤ 1h are acceptable (single-operator research tool)

### 10.4 Disaster recovery dry-run
- Quarterly: pretend Supabase is gone, restore to a fresh project,
  swap the backend's `SUPABASE_URL` + secrets, confirm `/system/status`
  goes green
- Annually: pretend the GitHub org is gone, clone from a local mirror,
  push to a new GitHub repo, confirm CI fires

---

## 11. Real-SSI failure-mode quick reference

One-line per failure mode for the real-SSI read-only dashboard. Full
diagnosis + fix lives in the troubleshooting playbook at
`self-deploy-preview.md` §11.2.

| Symptom | Most likely cause | Playbook |
|---|---|---|
| Browser XHRs go to `localhost:8000` or stale URL | `NEXT_PUBLIC_API_BASE_URL` not set or Pages not redeployed after env change | `self-deploy-preview.md` §11.2.1 |
| Login loops / every authed call returns 401 | Missing Supabase env on Pages OR `SUPABASE_JWT_SECRET` blank on backend | `self-deploy-preview.md` §11.2.2 |
| Browser console "blocked by CORS policy" | `CORS_ORIGINS` on backend doesn't list the Pages URL (must be JSON-array form) | `self-deploy-preview.md` §11.2.3 |
| `/market/live/quotes` rows show `source: "mock"` in production | Boot ran before secrets were finalised OR `APP_ENV` not actually `production` | `self-deploy-preview.md` §11.2.4 |
| `/system/status` lists missing SSI secrets OR `/market/status.status_code=AUTH_FAILED` | SSI consumer ID/secret unset or copy-pasted wrong | `self-deploy-preview.md` §11.2.5 |
| `/market/status.ready=false` outside the AUTH_FAILED case | RATE_LIMITED (slow the poller), ERROR (check upstream), STALE (outside market hours = expected) | `self-deploy-preview.md` §11.2.6 |
