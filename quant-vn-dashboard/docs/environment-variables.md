# Environment Variables Reference

## Overview

The dashboard splits configuration into two trust zones. Frontend variables
(prefixed `NEXT_PUBLIC_*`) are inlined into the browser bundle by Next.js at
build time and are safe to publish. Every other variable is server-only:
`apps/api` reads them through `Settings` in
`apps/api/src/core/config.py` via `pydantic-settings`, and they must live in
the API host's secret manager — never in Cloudflare Pages, never in a
client-side `.env`. The repo root `.env` is gitignored; copy `.env.example`
to `.env` to bootstrap local development. The settings loader looks first at
the monorepo-root `.env` and falls back to a `.env` in the API's working
directory.

When a server-side secret is missing, behaviour depends on `APP_ENV`. In
`production` the API refuses to start (`RuntimeError` raised by
`Settings.warn_if_missing_secrets`). In `development` or `staging` the
process boots, logs a `WARNING` listing each missing field, and routes that
depend on those secrets will respond with HTTP 503 until configured. The
required-for-production list is: `supabase_url`, `supabase_jwt_secret`,
`supabase_service_role_key`, `database_url`, `ssi_consumer_id`,
`ssi_consumer_secret`. Use `GET /system/status` at runtime to see the live
`missing_secrets` array.

## Frontend (`NEXT_PUBLIC_*`)

These ship to the browser. Configure them in Cloudflare Pages project
settings for production, and in the repo-root `.env` for local dev.

| Variable | Required | Default | Description |
| --- | --- | --- | --- |
| `NEXT_PUBLIC_API_BASE_URL` | Yes | `http://localhost:8000` | Base URL the web app uses for every `apps/api` request. Must point at the FastAPI host. |
| `NEXT_PUBLIC_SUPABASE_URL` | Yes | (none) | Supabase project URL used by `@supabase/ssr` for browser auth. |
| `NEXT_PUBLIC_SUPABASE_ANON_KEY` | Yes | (none) | Supabase anon key. Safe to expose; RLS gates everything. |

## Backend — core

| Variable | Required | Default | Description |
| --- | --- | --- | --- |
| `APP_ENV` | No | `development` | One of `development`, `staging`, `production`. Drives the fail-fast vs warn-only behaviour for missing secrets. |
| `API_HOST` | No | `0.0.0.0` | Bind address for `uvicorn`. |
| `API_PORT` | No | `8000` | Listen port for `uvicorn`. |
| `LOG_LEVEL` | No | `INFO` | Standard Python logging level (`DEBUG`, `INFO`, `WARNING`, `ERROR`). Applied at startup by `core.logging.configure_logging`. |
| `CORS_ORIGINS` | No | `["http://localhost:3000"]` | Allowed browser origins for the CORS middleware. See the format gotcha below. |

## Backend — Supabase

The API uses Supabase for auth (JWT verification) and as the app database.
The service-role key bypasses RLS and **must never** ship to the frontend or
appear in any `NEXT_PUBLIC_*` variable.

| Variable | Required | Default | Description |
| --- | --- | --- | --- |
| `SUPABASE_URL` | Yes (prod) | (empty) | Supabase project URL. |
| `SUPABASE_ANON_KEY` | No | (empty) | Public anon key. Mostly used by tests; routes prefer the user's bearer JWT. |
| `SUPABASE_SERVICE_ROLE_KEY` | Yes (prod) | (empty) | Server-only key used for trusted jobs that bypass RLS. Never expose. |
| `SUPABASE_JWT_SECRET` | Yes (prod) | (empty) | HS256 secret used to verify incoming user JWTs. Get it from Supabase → Project Settings → API. |
| `SUPABASE_DB_PASSWORD` | No | (empty) | Postgres password. Used to assemble `DATABASE_URL` if you keep them separate. |
| `DATABASE_URL` | Yes (prod) | (empty) | Full Postgres DSN, e.g. `postgresql://postgres:<pw>@db.<ref>.supabase.co:5432/postgres`. |

## Backend — SSI FastConnect

The API is the **only** SSI client. The frontend has no path to SSI.

| Variable | Required | Default | Description |
| --- | --- | --- | --- |
| `SSI_CONSUMER_ID` | Yes (prod) | (empty) | SSI FastConnect consumer ID. |
| `SSI_CONSUMER_SECRET` | Yes (prod) | (empty) | SSI FastConnect consumer secret. Server-only. |
| `SSI_BASE_URL` | No | `https://fc-data.ssi.com.vn` | Market data base URL. Override for staging/mock. |
| `SSI_TRADING_BASE_URL` | No | `https://fc-tradeapi.ssi.com.vn` | Trading API base URL. Read-only in Phase 1. |
| `SSI_TIMEOUT_SECONDS` | No | `10` | Per-request HTTP timeout (seconds, float). |
| `SSI_MAX_RETRIES` | No | `3` | Retry budget for transient SSI failures. |
| `SSI_USE_MOCK` | No | `false` | Set `true` to use the deterministic in-process mock provider. No SSI account required; ideal for first-clone development and tests. |
| `SSI_QUOTE_STALE_SECONDS` | No | `60` | Quotes older than this many seconds are returned with `stale: true`. The market routes apply this flag at response time. |

## Backend — Redis / Upstash

Used as the hot quote/index cache and (later) SSE pub/sub.

| Variable | Required | Default | Description |
| --- | --- | --- | --- |
| `REDIS_URL` | No | (empty) | Standard Redis URL, e.g. `redis://localhost:6379/0`. |
| `UPSTASH_REDIS_REST_URL` | No | (empty) | Upstash REST endpoint (alternative to `REDIS_URL`). |
| `UPSTASH_REDIS_REST_TOKEN` | No | (empty) | Upstash REST token. Server-only. |

If none of the Redis variables are set, `services.cache.build_cache` falls
back to an in-process in-memory cache. This is fine for single-process dev
but loses all cached state on restart and does not span workers — do not
run with the in-memory fallback in production.

## Backend — Market poller

The background poller fans out a single SSI subscription across the API and
fills the hot cache so dashboard tabs do not multiply SSI load. It is **off
by default** so the first `make dev-api` after cloning does not touch your
SSI quota.

| Variable | Required | Default | Description |
| --- | --- | --- | --- |
| `ENABLE_MARKET_POLLER` | No | `false` | Set `true` to start the background poller at API startup. |
| `MARKET_POLL_INTERVAL_SECONDS` | No | `15` | Cadence for the core symbol/index loop. |
| `FULL_MARKET_POLL_INTERVAL_SECONDS` | No | `300` | Cadence for the slower full-market refresh. |
| `QUOTE_CACHE_TTL_SECONDS` | No | `30` | TTL applied to quotes in the hot cache. |
| `INDEX_CACHE_TTL_SECONDS` | No | `30` | TTL applied to index snapshots in the hot cache. |
| `MARKET_CORE_SYMBOLS` | No | `FPT,MWG,HPG,VNM,VCB,VRE` | Always-polled symbols. CSV; SSE subscribers add their own on connect. |
| `MARKET_CORE_INDICES` | No | `VNINDEX,VN30` | Always-polled indices. CSV. |

Two additional knobs exist in `.env.example` but are also surfaced through
`Settings`: `WATCHLIST_POLL_INTERVAL_SECONDS` (default `10`) and
`TOP_MOVERS_CACHE_TTL_SECONDS` (default `60`). They tune the watchlist and
top-movers code paths.

## CORS_ORIGINS format gotcha

`pydantic-settings` parses values typed as `list[str]` by trying JSON first
and falling back to a per-field validator. The dashboard adds an explicit
CSV validator (`Settings._split_cors`), so both of these work in the
**process env**:

```
CORS_ORIGINS=http://localhost:3000,https://app.example.com
CORS_ORIGINS=["http://localhost:3000","https://app.example.com"]
```

In practice we standardise on the **JSON-array form** in production secret
managers because some shells and YAML loaders mangle commas inside CSV
strings, and a few tests in `apps/api/tests/` rely on the JSON form to
construct the settings cleanly. When in doubt, ship JSON.

## Validation behaviour at startup

`main.py` calls `settings.warn_if_missing_secrets()` inside the FastAPI
`lifespan`. The behaviour:

- **`APP_ENV=production`** — any missing required field raises
  `RuntimeError`; the process exits before serving traffic.
- **`APP_ENV` other than production** — the API logs a single `WARNING`
  listing each missing field and continues; dependent routes will respond
  `503 Service Unavailable` until the missing values are set.
- **All envs** — `GET /system/status` exposes a live `missing_secrets`
  array so operators can confirm without tailing logs.

A Phase 2 improvement is to make even `staging` fail-fast and to add a
readiness probe that asserts Redis reachability and JWKS fetchability
(currently only liveness is implemented at `GET /health`).

## Where variables are loaded from

In load order (later overrides earlier):

1. Defaults declared on `Settings` in `apps/api/src/core/config.py`.
2. The monorepo-root `.env` file (`<repo>/.env`).
3. A `.env` file in `apps/api/` if one exists.
4. Process environment variables exported by the shell, systemd unit,
   Docker `--env-file`, or your secret manager.

`pydantic-settings` reads each layer once and caches the result via
`functools.lru_cache` on `get_settings()`. Restart the API after changing
any variable — there is no hot reload of secrets.

## See also

- `.env.example` — copy-and-fill template at the repo root.
- `docs/deployment.md` — host-by-host placement of each secret.
- `docs/operations-runbook.md` — what to do when a secret needs rotating.
