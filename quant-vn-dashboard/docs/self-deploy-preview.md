# Self-deploy preview — single-page setup

This is the single English entry point for taking the dashboard from a
clean clone to a public preview URL. It consolidates the bits already
documented in:

- [`deployment.md`](deployment.md) — host placement matrix
- [`cloudflare-pages-setup.md`](cloudflare-pages-setup.md) — Pages config (Vietnamese, comprehensive)
- [`environment-variables.md`](environment-variables.md) — per-var reference
- [`production-runbook.md`](production-runbook.md) — rotation, smoke, rollback
- [`production-readiness-checklist.md`](production-readiness-checklist.md) — pre-promote ticklist

If you want depth on any one topic, follow the link. **This doc is the
shortest path.**

---

## Two modes

| Mode | When to use | Auth | SSI | Notes |
|---|---|---|---|---|
| **A. Preview (mock)** | First-time deploy validation, when you don't yet have SSI credentials | Supabase optional; can be deferred | Mock provider — deterministic synthetic data | `APP_ENV=staging` only. Production guard refuses `SSI_USE_MOCK=true` with `APP_ENV=production`. |
| **B. Real SSI read-only** | First public release with live data | Supabase required | Real SSI FastConnect Data | `APP_ENV=production` + `SSI_USE_MOCK=false`. **No live trading, no auto-trading** — gates in code refuse. |

Always start with Mode A to validate the deploy pipeline, then promote to Mode B
once SSI + Supabase credentials are in your hands.

---

## 1. Cloudflare Pages (frontend)

### 1.1 Project settings (enter exactly as shown)

| Field | Value | Notes |
|---|---|---|
| Project name | `quant-vn` (or your own; lowercase + hyphens) | Becomes the URL prefix on `*.pages.dev` |
| Production branch | `main` | |
| Framework preset | **Next.js** | The Pages Next.js adapter (not "Static HTML"). The frontend uses the App Router with one Node-runtime BFF route (`/api/stream/[...path]`). |
| **Root directory** | `quant-vn-dashboard` | Repo root sits one level up. |
| **Build command** | `cd apps/web && pnpm install --frozen-lockfile=false && pnpm build` | The web app lives in `apps/web/`. |
| **Build output directory** | `apps/web/.next` | |
| Node version | `20` | Set via the `NODE_VERSION` env var below. |

### 1.2 Environment variables — Production

Set these in Cloudflare Pages → **Settings → Environment variables → Production**.

| Var | Mode A (preview) | Mode B (real SSI) | Notes |
|---|---|---|---|
| `NEXT_PUBLIC_API_BASE_URL` | `https://<your-fly-app>.fly.dev` | Same — Fly URL or your custom domain | The frontend's only outbound API target. |
| `NEXT_PUBLIC_APP_ENV` | `staging` | **`production`** | Activates Phase 2A no-silent-mock-fallback in `useAsyncResource`. |
| `NEXT_PUBLIC_SUPABASE_URL` | `https://<ref>.supabase.co` (optional in A) | Required | Supabase project URL. |
| `NEXT_PUBLIC_SUPABASE_ANON_KEY` | empty OK in A | Required (`sb_publishable_…`) | Anon/publishable key. Safe to publish. |
| `NODE_VERSION` | `20` | `20` | Pages defaults to 18; Next 15 needs ≥20. |

### 1.3 NEVER set on Pages

These are server-only. The build-time inliner would bake them into the browser bundle:

```
SSI_CONSUMER_ID                 SSI_CONSUMER_SECRET
SSI_TRADING_CONSUMER_ID         SSI_TRADING_CONSUMER_SECRET
SUPABASE_SERVICE_ROLE_KEY       SUPABASE_JWT_SECRET
UPSTASH_REDIS_REST_TOKEN        REDIS_URL
DATABASE_URL                    AUTO_TRADE_WORKER_SECRET
SUPABASE_DB_PASSWORD
```

A CI `gitleaks` workflow guards the repo; you guard the Pages env.

### 1.4 Deploy

Push to `main` → Pages auto-builds a preview deployment → inspect →
**manual promote to production** via the Pages dashboard. Do not enable
auto-promotion.

---

## 2. Backend — Fly.io (primary)

Fly.io is recommended because (a) Singapore region (`sin`) is closest to
SSI's Vietnamese datacenter, (b) SSE survives long-lived connections,
(c) `flyctl secrets set` is the simplest secret manager.

### 2.1 First-time setup

```bash
# Once per workstation:
brew install flyctl                    # macOS; see https://fly.io/docs/flyctl/install
flyctl auth signup                     # or `flyctl auth login` if you already have an account

# From the repo root:
cd quant-vn-dashboard/apps/api
flyctl launch --name quant-vn-api --region sin --no-deploy
# Accept defaults; do NOT add Postgres (Supabase is the DB).
# Do NOT add Redis if you plan to use Upstash REST.
```

`fly launch` writes a `fly.toml` to `apps/api/`. Review it; commit it
once you're happy with the region + scale settings.

### 2.2 Mode A — Preview (mock) secrets

```bash
flyctl secrets set \
  APP_ENV=staging \
  CORS_ORIGINS='["https://<your-pages-url>"]' \
  SSI_USE_MOCK=true \
  --app quant-vn-api
```

Mode A boots without any SSI / Supabase secrets — the dashboard renders
mock data; auth fails gracefully.

### 2.3 Mode B — Real SSI read-only secrets

```bash
flyctl secrets set \
  APP_ENV=production \
  CORS_ORIGINS='["https://<your-pages-url>"]' \
  SSI_USE_MOCK=false \
  SSI_CONSUMER_ID=<from SSI portal> \
  SSI_CONSUMER_SECRET=<from SSI portal> \
  SUPABASE_URL=https://<ref>.supabase.co \
  SUPABASE_JWT_SECRET=<from Supabase Settings → API → JWT secret> \
  SUPABASE_SERVICE_ROLE_KEY=sb_secret_… \
  DATABASE_URL='postgresql://postgres:<pw>@db.<ref>.supabase.co:5432/postgres' \
  SSI_TRADING_USE_MOCK=true \
  SSI_TRADING_READ_ONLY=true \
  SSI_TRADING_ORDER_PLACEMENT_ENABLED=false \
  TRADING_LIVE_ORDER_ENABLED=false \
  TRADING_ORDER_PLACEMENT_DRY_RUN=true \
  AUTO_TRADE_LIVE_ENABLED=false \
  AUTO_TRADE_ORDER_PLACEMENT_ENABLED=false \
  AUTO_TRADE_WORKER_ENABLED=false \
  AUTO_TRADE_DRY_RUN=true \
  --app quant-vn-api
```

The `_assert_production_*` startup guards in `core/config.py` will
refuse to boot if any of the trailing flags drift from these values.
That's the design — a misconfiguration fails closed.

### 2.4 Deploy

```bash
flyctl deploy --image-label "$(git rev-parse --short HEAD)" --app quant-vn-api
flyctl status --app quant-vn-api          # confirm healthy
flyctl logs --app quant-vn-api            # tail boot logs; look for guard errors
```

If a guard raises `RuntimeError` at boot, fix the secret and redeploy.
Don't bypass the guard.

---

## 3. Backend — cheap VPS (fallback)

Use this path only if Fly.io is unavailable. Examples in
[`deployment.md`](deployment.md) cover GCP e2-micro + Docker; the same
recipe works on any 1-vCPU/512MB-RAM VPS.

Skeleton:

```bash
# 1. On the VPS, install Docker.
curl -fsSL https://get.docker.com | sh

# 2. Clone the repo + cd into the API dir.
git clone <your-repo-url> Quant_Finance
cd Quant_Finance/quant-vn-dashboard/apps/api

# 3. Build the image.
docker build -t quant-vn-api:local .

# 4. Run with an env file (NEVER commit it).
cat > .env.production <<'EOF'
APP_ENV=production
CORS_ORIGINS=["https://<your-pages-url>"]
SSI_USE_MOCK=false
# … fill the rest per §2.3
EOF
chmod 600 .env.production

docker run -d --restart=always \
  --name quant-vn-api \
  -p 127.0.0.1:8000:8000 \
  --env-file .env.production \
  quant-vn-api:local

# 5. Front with nginx + Let's Encrypt TLS termination.
# (Out of scope for this doc; see deployment.md §"VPS+nginx".)
```

---

## 4. Supabase

| Step | Where |
|---|---|
| 1. Create project | https://supabase.com/dashboard |
| 2. Get URL, anon (publishable) key, service role key, JWT secret, DB password | Settings → API + Settings → Database |
| 3. Apply migrations | Supabase SQL editor → run each `db/migrations/*.sql` in numeric order |
| 4. Enable RLS | Already encoded in the migrations |
| 5. Configure auth providers | Authentication → Providers — magic link or password+email confirmation |
| 6. Disable anonymous sign-up if you don't want it | Authentication → Settings |

---

## 5. Cache — Upstash Redis (optional)

For Mode A you can skip Redis entirely — the API falls back to an
in-process LRU. For Mode B with multiple symbols or live SSE, set up
Upstash:

| Step | Where |
|---|---|
| 1. Create a Redis database (Global, ap-southeast-1 region) | https://console.upstash.com |
| 2. Copy REST URL + REST Token | Database → Details |
| 3. Set on backend host only | `flyctl secrets set UPSTASH_REDIS_REST_URL=… UPSTASH_REDIS_REST_TOKEN=… --app quant-vn-api` |

The poller and the quote cache will pick it up automatically.

---

## 6. Local commands — operator checklist

Run these from the workstation (not the deployed host).

| Step | Command | Why |
|---|---|---|
| 1 | `cd quant-vn-dashboard` | Always start at the dashboard root. |
| 2 | `cp .env.example .env` | Bootstrap local dev env. Edit values; leave secrets blank if you don't have them. |
| 3 | `make install` | Installs API (pip editable) + web (pnpm). |
| 4 | `make dev-api` (one terminal) | Boots FastAPI on `:8000` with auto-reload. |
| 5 | `make dev-web` (another terminal) | Boots Next.js on `:3000`. |
| 6 | Open `http://localhost:3000` | Verify the local stack runs before deploying anything. |
| 7 | `cd apps/api && python3 -m pytest tests/ -q` | Full backend suite (~30s). |
| 8 | `cd apps/web && pnpm typecheck && pnpm test` | Frontend typecheck + vitest. |
| 9 | Push to `main` | Cloudflare Pages auto-builds the preview deploy. |
| 10 | `flyctl deploy --app quant-vn-api` | Deploy backend. |
| 11 | `make deploy-check API_BASE_URL=https://… JWT=…` | Post-deploy smoke (4 release gates). |

---

## 7. Smoke tests

### 7.1 One-command (preferred)

```bash
API_BASE_URL=https://<your-fly-app>.fly.dev \
JWT=<paste a fresh Supabase access token> \
  make deploy-check
```

`make deploy-check` validates the env vars, runs `scripts/production-smoke.sh`,
and exits non-zero on any failure. The script is read-only and never
logs the JWT.

### 7.2 Manual fallback (if the script can't run)

```bash
API="https://<your-fly-app>.fly.dev"
JWT="<paste>"

# Liveness — no auth.
curl -fsS "$API/health" | jq .                          # expect: {"status":"ok"}

# Missing secrets must be empty.
curl -fsS -H "Authorization: Bearer $JWT" \
     "$API/system/status" | jq '.missing_secrets'        # expect: []

# SSI provider readiness (Mode B).
curl -fsS -H "Authorization: Bearer $JWT" \
     "$API/market/status" | jq '.ready'                  # expect: true

# Real quotes during market hours (09:00–15:00 ICT, Mon–Fri).
curl -fsS -H "Authorization: Bearer $JWT" \
     "$API/market/live/quotes?symbols=FPT,MWG,HPG" | \
     jq '.[] | {symbol, source, price, stale}'           # expect: source: "ssi" or "cache"
```

Any non-200 or a `source=mock` row in production = **do not promote**.
Roll back per `production-runbook.md` §7.

---

## 8. Mode A → Mode B switchover

When SSI + Supabase credentials are ready and you want to promote
preview → real-SSI:

```bash
# 1. Rotate the 5 historical secrets first (mvp-v0.1-acceptance.md B3).

# 2. Flip backend to production-real-SSI on Fly:
flyctl secrets set \
  APP_ENV=production \
  SSI_USE_MOCK=false \
  SSI_CONSUMER_ID=… \
  SSI_CONSUMER_SECRET=… \
  SUPABASE_URL=… \
  SUPABASE_JWT_SECRET=… \
  SUPABASE_SERVICE_ROLE_KEY=… \
  DATABASE_URL=… \
  --app quant-vn-api
# Fly auto-redeploys; production guards fire at boot.

# 3. Update Pages env: NEXT_PUBLIC_APP_ENV=production.
#    Pages dashboard → Settings → Env vars → Production → edit → save → redeploy.

# 4. Smoke:
make deploy-check API_BASE_URL=https://<fly>.fly.dev JWT=<token>
# exit 0 = real SSI data flowing.

# 5. Tick the green-phase boxes in production-readiness-checklist.md.
```

---

## 9. What will NOT work yet (by design)

| Surface | Reason |
|---|---|
| Live order submission | `_assert_production_order_placement_disabled` refuses prod boot if enabled. Phase 3 milestone. |
| Auto-trade live mode | `_assert_production_auto_trade_disabled` refuses prod boot if enabled. Phase 3 milestone. |
| SSI Trading read-only routes | Provider stub returns 501 in real mode. `SSI_TRADING_USE_MOCK=true` is the supported value. |
| Phase 2.B fundamentals gating | Provider + math landed but route layer isn't wired yet. Recommendations still ignore ROE / net profit / audit opinion. |
| Daily-loss / position-weight risk caps | Captured in settings; portfolio MTM service is the Phase 2.10 milestone. |

These are deliberate gaps. **Do not enable them by flag-flipping** —
the production guards will refuse to boot.

---

## 10. Cross-references

- Rotate a leaked secret: `production-runbook.md` §4
- Emergency stop: `production-runbook.md` §6
- Pre-promotion ticklist: `production-readiness-checklist.md`
- Branch protection + CI gates: `harness-code-governance.md`
- Per-var env reference: `environment-variables.md`
- Detailed Vietnamese Pages walk-through: `cloudflare-pages-setup.md`

---

## 11. Real-SSI read-only dashboard mode

This is the operator-grade troubleshooting playbook for **Mode B**
(real SSI FastConnect Data, no live trading, no auto-trade). Pair it
with the smoke script — `make deploy-check` is the single check that
covers all four release gates; the playbook here is what to do when
that check fails.

### 11.1 Required env at a glance

**Backend (Fly.io / VPS host secret manager — never on Pages):**

```env
# Core
APP_ENV=production
CORS_ORIGINS=["https://<your-pages-url>"]
SSI_USE_MOCK=false
SSI_CONSUMER_ID=<from SSI FastConnect portal>
SSI_CONSUMER_SECRET=<from SSI FastConnect portal>

# Supabase (server-only — never on Pages)
SUPABASE_URL=https://<ref>.supabase.co
SUPABASE_JWT_SECRET=<from Supabase Settings → API → JWT secret>
SUPABASE_SERVICE_ROLE_KEY=<from Supabase Settings → API → service_role>
DATABASE_URL=postgresql://postgres:<pw>@db.<ref>.supabase.co:5432/postgres

# Poller (recommended for stable quote latency in the UI)
ENABLE_MARKET_POLLER=true
QUOTE_CACHE_TTL_SECONDS=30
INDEX_CACHE_TTL_SECONDS=30
MARKET_POLL_INTERVAL_SECONDS=15
MARKET_CORE_SYMBOLS=FPT,MWG,HPG,VNM,VCB,VRE
MARKET_CORE_INDICES=VNINDEX,VN30

# Optional cache (use Upstash REST or a managed Redis — not both)
REDIS_URL=<optional>
UPSTASH_REDIS_REST_URL=<optional>
UPSTASH_REDIS_REST_TOKEN=<optional>

# Trading + auto-trade — these MUST stay at the values below.
# The production startup guard in core/config.py refuses to boot
# if any of them are flipped. Do not change.
TRADING_LIVE_ORDER_ENABLED=false
TRADING_MANUAL_CONFIRM_ENABLED=false
TRADING_ORDER_PLACEMENT_DRY_RUN=true
SSI_TRADING_ORDER_PLACEMENT_ENABLED=false
SSI_TRADING_READ_ONLY=true
SSI_TRADING_USE_MOCK=true
AUTO_TRADE_ENABLED=false
AUTO_TRADE_LIVE_ENABLED=false
AUTO_TRADE_ORDER_PLACEMENT_ENABLED=false
AUTO_TRADE_DRY_RUN=true
AUTO_TRADE_WORKER_ENABLED=false
AUTO_TRADE_DEFAULT_MODE=OFF
```

**Cloudflare Pages (Production):**

```env
NEXT_PUBLIC_API_BASE_URL=https://<your-fly-app>.fly.dev
NEXT_PUBLIC_SUPABASE_URL=https://<ref>.supabase.co
NEXT_PUBLIC_SUPABASE_ANON_KEY=<sb_publishable_…>
NEXT_PUBLIC_APP_ENV=production
NEXT_TELEMETRY_DISABLED=1
NODE_VERSION=20
```

**NEVER on Pages** (these belong on the backend only and would be
inlined into the browser bundle if set here):

```
SSI_CONSUMER_ID                  SSI_CONSUMER_SECRET
SSI_TRADING_CONSUMER_ID          SSI_TRADING_CONSUMER_SECRET
SUPABASE_SERVICE_ROLE_KEY        SUPABASE_JWT_SECRET
DATABASE_URL                     SUPABASE_DB_PASSWORD
REDIS_URL                        UPSTASH_REDIS_REST_TOKEN
AUTO_TRADE_WORKER_SECRET         PRIVATE_KEY (any)
```

### 11.2 Troubleshooting playbook

Six failure modes. Each row: **symptom → diagnosis → fix**.

#### 11.2.1 Frontend points to the wrong backend

| | |
|---|---|
| **Symptom** | Browser DevTools → Network shows XHR to `localhost:8000` or to a stale preview URL. Login may also fail with a CORS error. |
| **Diagnose** | DevTools → Network → click any XHR → check the request URL host. Compare to `NEXT_PUBLIC_API_BASE_URL` on Pages. |
| **Fix** | Cloudflare Pages → Settings → Environment variables → Production → edit `NEXT_PUBLIC_API_BASE_URL` to your Fly URL `https://<app>.fly.dev`. **Re-deploy** the Pages site (env changes don't take effect until the next build — push a no-op commit or click "Retry deployment"). |
| **Prevent** | After deploy, run `make deploy-check API_BASE_URL=https://<fly> JWT=…` — it hits the backend directly so a wrong-URL frontend cannot mask a working backend. |

#### 11.2.2 Missing Supabase env (login loops or 401)

| | |
|---|---|
| **Symptom** | Magic-link click returns to the dashboard but the user object is null; every authenticated XHR returns 401. |
| **Diagnose** | DevTools → Application → Local Storage → look for the `sb-<ref>-auth-token` key. If absent: Pages env is missing the Supabase URL or anon key. If present but XHRs still 401: backend is missing `SUPABASE_JWT_SECRET` (it can't verify the token). |
| **Fix** | Pages-side: set `NEXT_PUBLIC_SUPABASE_URL` + `NEXT_PUBLIC_SUPABASE_ANON_KEY` then re-deploy. Backend-side: `flyctl secrets set SUPABASE_JWT_SECRET=… SUPABASE_URL=… SUPABASE_SERVICE_ROLE_KEY=… DATABASE_URL=…` then Fly auto-redeploys. |
| **Prevent** | `curl -fsS -H "Authorization: Bearer $JWT" $API/system/status \| jq .missing_secrets` returns `[]` only when all four Supabase backend secrets are present. |

#### 11.2.3 Backend CORS rejection

| | |
|---|---|
| **Symptom** | Browser console: `Access to fetch at 'https://api.../system/status' from origin 'https://...pages.dev' has been blocked by CORS policy`. Backend logs show `403` on the OPTIONS preflight. |
| **Diagnose** | `flyctl ssh console --app quant-vn-api` then `echo $CORS_ORIGINS` — confirm it's a JSON-array string that contains the exact Pages URL (including scheme; no trailing slash). |
| **Fix** | `flyctl secrets set CORS_ORIGINS='["https://<your-pages-url>"]' --app quant-vn-api`. Note: JSON-array form preferred — some shells mangle commas in CSV form. Fly will roll the app. |
| **Prevent** | The `_assert_production_cors` boot guard refuses to start with localhost-only or wildcard CORS — so a misconfiguration fails closed at deploy time, not silently at request time. |

#### 11.2.4 `SSI_USE_MOCK` accidentally true in production

| | |
|---|---|
| **Symptom** | The backend boots successfully but `/market/live/quotes` returns rows with `source: "mock"` and the smoke script exits non-zero with "Quote endpoint returned N mock-sourced row(s)". |
| **Diagnose** | Either (a) `APP_ENV` is not actually `production` (the no-mock guard only fires in production), or (b) the SSI provider failed to construct and the route is using mock as a fallback (it should not — verify by reading `flyctl logs`). |
| **Fix** | Two-step. First confirm `flyctl secrets list --app quant-vn-api` shows `APP_ENV=production` and `SSI_USE_MOCK=false`. If both are correct but the rows still say `mock`, that's a deploy-snapshot mismatch — `flyctl deploy --app quant-vn-api` to force a redeploy. |
| **Prevent** | `_assert_production_ssi_real_mode` raises `RuntimeError` on boot if `SSI_USE_MOCK=true` and `APP_ENV=production`. If the backend is up, this guard already passed — the `mock` rows must therefore come from a build that booted before secrets were finalised; redeploy. |

#### 11.2.5 SSI credentials missing or invalid

| | |
|---|---|
| **Symptom** | `/system/status` → `missing_secrets` includes `ssi_consumer_id` or `ssi_consumer_secret` (missing), OR `/market/status` returns `status_code: "AUTH_FAILED"` (invalid). |
| **Diagnose** | `curl -fsS -H "Authorization: Bearer $JWT" $API/system/status \| jq '.missing_secrets'` for missing. For invalid: `curl -fsS -H "Authorization: Bearer $JWT" $API/market/status \| jq '{status_code, mode, last_error_sanitized}'`. |
| **Fix (missing)** | `flyctl secrets set SSI_CONSUMER_ID=… SSI_CONSUMER_SECRET=… --app quant-vn-api`. |
| **Fix (invalid)** | Confirm the values match the SSI FastConnect Data portal exactly (no leading/trailing whitespace, no quote stripping). Re-paste from the portal. If still rejected, regenerate the secret in the portal, repeat. |
| **Prevent** | In production the missing-secrets guard fails the boot — so the API will never serve traffic with these blank. Invalid credentials surface only at first SSI call; the smoke script catches them within 5 seconds. |

#### 11.2.6 `/market/status` not ready (provider not connected)

| | |
|---|---|
| **Symptom** | `/health` returns `{"status":"ok"}`, `/system/status` shows no missing secrets, but `/market/status` returns `ready: false` with `status_code` of `RATE_LIMITED`, `ERROR`, or `STALE`. |
| **Diagnose** | The shape of `last_error_sanitized` tells you which class. `RATE_LIMITED` = SSI throttling; back off poll cadence. `ERROR` = network or upstream 5xx; check SSI status page. `STALE` = last successful call older than the freshness window (typical outside market hours). |
| **Fix (`RATE_LIMITED`)** | Lower `MARKET_POLL_INTERVAL_SECONDS` is the wrong direction — raise it to reduce the per-second call rate. Try `MARKET_POLL_INTERVAL_SECONDS=30` and confirm via `/market/status` after a minute. |
| **Fix (`ERROR`)** | Tail `flyctl logs --app quant-vn-api` and look for the underlying HTTP status from SSI. 502/503 = SSI side; wait. 401/403 = credential issue; revisit §11.2.5. |
| **Fix (`STALE`)** | Outside market hours (09:00–15:00 ICT Mon–Fri) this is expected; do not page yourself. During market hours, restart the poller: `flyctl apps restart quant-vn-api`. |
| **Prevent** | During market hours the smoke script exits non-zero on `ready=false`; outside market hours quotes are stale by definition — don't treat `stale: true` as a deploy blocker outside trading windows. |

### 11.3 Verification checklist for first Mode B boot

After flipping the backend to real SSI and re-deploying:

1. `flyctl status --app quant-vn-api` → expect `running`, no recent restarts
2. `flyctl logs --app quant-vn-api | grep -E "RuntimeError|Refusing"` → expect 0 matches
3. `make deploy-check API_BASE_URL=https://<fly> JWT=<token>` → expect exit 0
4. Open the Pages URL → login → land on Dashboard → confirm Network XHRs hit the Fly URL
5. DevTools → Network → search any response body for `sb_secret_`, `eyJhbGciOiJIUzI1NiI` outside the `Authorization` header → expect 0 hits
6. Tick the 🟢-marked boxes in `production-readiness-checklist.md`

If any step fails, return to the relevant §11.2.X playbook entry.
