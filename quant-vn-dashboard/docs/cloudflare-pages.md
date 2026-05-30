# Cloudflare Pages — Phase 2A Public Deploy

Phase 2A makes the Quant VN Dashboard publicly accessible (login-gated) with
the Next.js frontend hosted on **Cloudflare Pages** and the FastAPI backend
running on a long-lived host (GCP e2-micro, Fly.io, or cheap VPS — see
[`deployment.md`](./deployment.md)).

This doc is specific to **frontend** deployment. For the backend, see
`deployment.md` "FastAPI backend on …" sections.

## Why Cloudflare Pages (and not Workers / Vercel Edge)

- The frontend is **pure Next.js static + RSC output** — no SSE on the
  frontend host. SSE lives on the FastAPI backend.
- Pages gives free SSL + global CDN + preview deploys per PR + an automatic
  build pipeline triggered by `git push`.
- **Do NOT** host the FastAPI app as a Cloudflare Worker — SSE needs a
  long-lived connection that the Worker timeout will kill.

## Build settings

| Setting | Value |
|---|---|
| Framework preset | Next.js |
| Production branch | `main` |
| Build command | `cd apps/web && pnpm install --frozen-lockfile=false && pnpm build` |
| Build output directory | `apps/web/.next` |
| Root directory | `quant-vn-dashboard` |
| Node version | `20` (set `NODE_VERSION=20` in env vars) |
| Package manager | `pnpm` (Pages detects from `package.json` / lockfile) |

## Allowed environment variables (set in Cloudflare Pages project → Settings → Environment variables)

Phase 2A locks the frontend env list to these and **forbids every backend
secret**. The forbidden list below mirrors the project's threat model.

### Required

| Variable | Example | Notes |
|---|---|---|
| `NEXT_PUBLIC_API_BASE_URL` | `https://api.quantvn.example.com` | Must be HTTPS in production; must match a `CORS_ORIGINS` entry on the backend |
| `NEXT_PUBLIC_SUPABASE_URL` | `https://<project>.supabase.co` | Public — safe to ship to browsers |
| `NEXT_PUBLIC_SUPABASE_ANON_KEY` | `sb_publishable_...` | Public — RLS enforces row isolation |
| `NEXT_PUBLIC_APP_ENV` | `production` | Drives any env-aware UI (e.g. dev-only mock badges suppressed) |

### Forbidden in frontend env (Cloudflare Pages)

If any of these accidentally land in Cloudflare Pages env vars, **rotate the
secret immediately** — Cloudflare Pages env vars are visible to anyone with
project access AND get baked into the Worker bundle that ships to browsers:

| Forbidden | Why |
|---|---|
| `SSI_CONSUMER_ID` | SSI market-data auth — backend-only |
| `SSI_CONSUMER_SECRET` | Same |
| `SSI_TRADING_CONSUMER_ID` | Phase-2 trading placeholder — never instantiated, never exposed |
| `SSI_TRADING_CONSUMER_SECRET` | Same |
| `SUPABASE_SERVICE_ROLE_KEY` | Bypasses RLS — backend-only |
| `SUPABASE_JWT_SECRET` | Used to verify user JWTs server-side |
| `UPSTASH_REDIS_REST_TOKEN` | Read/write access to the hot cache |
| `REDIS_URL` | Same |
| `DATABASE_URL` | Direct Postgres credentials |

The frontend literally cannot use these — there's no code path under
`apps/web/src/` that imports them, and the `no-direct-ssi.test.ts` +
`test_no_hardcoded_secrets_in_production_source` regression tests fail loud
if they ever appear.

## Pages preview vs production

| Environment | Triggered by | Env var override |
|---|---|---|
| Production | push to `main` | Uses the **Production** env-var set |
| Preview | push to any other branch / open PR | Uses the **Preview** env-var set |

Recommended pattern: point Preview at a **staging backend** (`APP_ENV=staging`,
its own Supabase project, its own SSI credentials or `SSI_USE_MOCK=true`)
so PR previews never touch production data.

The backend enforces this asymmetrically — Phase 2A `core/config.py` will
**refuse to start in production with `SSI_USE_MOCK=true`** (verified by
`test_production_refuses_ssi_use_mock_true`). Staging is allowed to mock.

## Custom domain

```
Cloudflare Pages → Custom domains → Add custom domain
  → dashboard.quantvn.example.com  → CNAME the apex record
```

After provisioning:
1. Update the backend's `CORS_ORIGINS` to include the custom domain:
   `CORS_ORIGINS=["https://dashboard.quantvn.example.com","https://<project>.pages.dev"]`
2. Update `NEXT_PUBLIC_API_BASE_URL` if the API moved (e.g. to a
   `api.quantvn.example.com` CNAME).
3. Re-deploy both ends.

## Auth flow on Cloudflare

- The frontend uses Supabase Auth via `@supabase/ssr` cookies. Cloudflare
  Pages preserves cookies on the edge — no special config needed.
- The Pages middleware (`apps/web/src/middleware.ts`) redirects
  unauthenticated requests to `/login?redirectTo=...` and is statically
  embedded in the bundle.
- The backend verifies the Supabase JWT via HS256 (`core/security.py`).
  When you rotate `SUPABASE_JWT_SECRET`, **every existing user session is
  invalidated** — plan rotation for a maintenance window.

## Smoke test (run after first prod deploy)

Mirrors the 8-item production smoke checklist in `deployment.md`:

1. `curl https://api.quantvn.example.com/health` → `{"status": "ok"}`
2. Open `https://dashboard.quantvn.example.com` → login page renders
3. Sign in via Supabase Auth → redirected to `/dashboard`
4. Open `/market` → index cards render with **real prices** (no "Mock Data" badge)
5. Open `/data-quality` → `provider.name="ssi"`, `provider.mock=false`,
   `provider.ready=true`
6. DevTools → Network → filter `ssi.com.vn` → **zero** matches (frontend
   never calls SSI directly)
7. DevTools → Network → spot-check any XHR body → no Supabase service-role
   key, no JWT in plain text outside the `Authorization` header, no SSI
   consumer secret
8. `curl -i -X POST https://api.quantvn.example.com/portfolio/sync/ssi
   -H "Authorization: Bearer <jwt>"` → `HTTP 501` with the Phase-2
   placeholder body

If any check fails, see the `deployment.md` failure-mode escalation table.

## CDN / cache behaviour

- Cloudflare Pages serves static assets (`/_next/static/*`) with
  far-future cache headers — no config needed.
- API calls (`/portfolio/*`, `/market/*`, `/recommendations/*`, etc.) go
  to `NEXT_PUBLIC_API_BASE_URL` directly from the browser — they do NOT
  pass through the Pages edge. The backend must handle its own auth +
  rate limiting.
- SSE streams (`/stream/quotes`, `/stream/watchlist/{id}`, etc.) also
  bypass Pages. The backend's nginx/Fly.io config must disable buffering
  on these routes (`proxy_buffering off` — already in the deployment doc).

## Rollback

```
Cloudflare Pages → Deployments → pick a previous green deploy
  → "Rollback to this deployment"
```

This is a one-click revert. Backend rollback is independent — see
`deployment.md` (Fly.io: `fly releases revert <id>`; systemd: redeploy
previous container tag).

## Known limitations

- Cloudflare Pages does **not** support long-lived WebSocket / SSE
  connections from the Pages host itself. Our architecture intentionally
  routes SSE through the FastAPI backend (`/stream/*`), so this isn't a
  blocker — but if you ever consider hosting the FastAPI app on a Pages
  Function, **do not** — the timeout will break SSE.
- Pages auto-builds on every push to `main`. There is no manual gate. If
  the GitHub Actions `frontend-build.yml` workflow is green, Pages will
  pick up the same commit a few minutes later.
- Phase 2A intentionally does NOT add `getServerSideProps` / Edge
  runtime patterns — those would couple us to specific hosts. The frontend
  remains a pure static + RSC build that runs on any static host.
