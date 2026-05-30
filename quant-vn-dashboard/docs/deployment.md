# Deployment

MVP hosting model:

| Component      | Host                                | Notes                                    |
| -------------- | ----------------------------------- | ---------------------------------------- |
| `apps/web`     | Cloudflare Pages                    | Next.js frontend deployment target.      |
| `apps/api`     | GCP e2-micro / cheap VPS            | Must be long-lived for FastAPI SSE.      |
| Worker poller  | Same host as `apps/api`             | Single process owns the SSI subscription.|
| Postgres       | Supabase                            | Auth + app data; enable RLS.             |
| Redis          | Upstash                             | Hot cache + pub/sub.                     |
| Storage (DuckDB)| Local disk on API host             | Read-only at runtime; refresh from EOD.  |

> Cloudflare Pages should host only the frontend. Do not host the API as a
> short-lived serverless function because SSE requires long-lived connections,
> which serverless functions do not support.

## Environment variables

See `.env.example` at the repo root. At deploy time:

1. Set every `NEXT_PUBLIC_*` var in **Cloudflare Pages project settings**.
2. Set every server-only var (`SSI_*`, `SUPABASE_SERVICE_ROLE_KEY`,
   `SUPABASE_JWT_SECRET`, `SUPABASE_DB_PASSWORD`, `DATABASE_URL`, `REDIS_URL`)
   in the **API host's secret manager** — never in frontend settings.
3. CORS_ORIGINS must include your production Cloudflare Pages URL.

## Build & run

```bash
# API container
cd apps/api
docker build -t quant-vn-api .
docker run -p 8000:8000 --env-file ../../.env quant-vn-api

# Web (Cloudflare Pages auto-builds on git push; local prod build:)
cd apps/web
pnpm install
pnpm build
pnpm start
```

## Healthchecks

- Liveness: `GET /health` → 200.
- Readiness (later): asserts Redis reachable and Supabase JWKS fetchable.

## Backups

- Supabase Postgres: daily PITR (built-in).
- DuckDB / parquet: source-of-truth is the upstream provider; re-ingest from
  `datapipe/` if lost.

## Rollback

- Web: Cloudflare Pages deployment rollback.
- API: redeploy previous container tag. No DB migrations means a redeploy
  alone is sufficient for code-only changes.

---

## Local development

Step-by-step from a clean clone to a running dev stack.

```bash
# 1. Clone and enter the dashboard
git clone <repo-url> Quant_Finance
cd Quant_Finance/quant-vn-dashboard

# 2. Copy env template and fill in values (Supabase + SSI keys)
cp .env.example .env
# Edit .env — at minimum set SUPABASE_*, NEXT_PUBLIC_SUPABASE_*, and either
# real SSI_CONSUMER_* secrets OR SSI_USE_MOCK=true for a no-credential setup.

# 3. Install both apps
make install        # runs install-api + install-web

# 4. Bring up Redis (optional — REDIS_URL blank falls back to in-memory)
docker compose up -d redis

# 5. Run dev servers in two terminals
make dev-api        # FastAPI on :8000  (uvicorn --reload)
make dev-web        # Next.js on :3000
```

Smoke test:

```bash
curl -s http://localhost:8000/system/health
curl -s http://localhost:8000/recommendations/symbol/FPT | jq .
open http://localhost:3000
```

### Docker compose local

The compose file ships two services and the `api` service is gated behind a
profile so the default `docker compose up` only starts Redis:

```bash
# Redis only — for use with `make dev-api`
docker compose up -d redis

# API + Redis (uses apps/api/Dockerfile)
docker compose --profile api up --build
```

Stop everything: `docker compose --profile api down`.

---

## Cloudflare Pages (frontend)

Cloudflare Pages hosts `apps/web` only. The API stays on a long-lived host
(SSE will not survive a short-lived edge function).

1. Cloudflare dashboard → **Workers & Pages → Create → Pages → Connect to Git**.
2. Pick this repo, set the **production branch** to `main`.
3. **Build configuration**:
   - Framework preset: **Next.js** (the Pages Next.js adapter, not "static HTML").
   - Build command: `cd quant-vn-dashboard/apps/web && pnpm install && pnpm build`
   - Build output directory: `quant-vn-dashboard/apps/web/.next`
   - Root directory: leave blank (we cd in the build command).
4. **Environment variables → Production** (set in the Pages project, not in git):
   - `NODE_VERSION=20`
   - `NEXT_PUBLIC_API_BASE_URL=https://api.<your-domain>`
   - `NEXT_PUBLIC_SUPABASE_URL=https://<project>.supabase.co`
   - `NEXT_PUBLIC_SUPABASE_ANON_KEY=<anon-key>`
   - Optional: `NEXT_TELEMETRY_DISABLED=1`
5. Trigger a deployment. Pages will auto-redeploy on every push to `main`.

> Only `NEXT_PUBLIC_*` vars belong here. Never paste service-role keys, SSI
> secrets, or `SUPABASE_JWT_SECRET` into Pages settings — they would be
> bundled into the client.

---

## FastAPI backend on GCP e2-micro or cheap VPS

The API must stay long-lived because of SSE. A single small VM (GCP e2-micro,
Hetzner CX11, Vultr $5, etc.) is enough for MVP.

### One-time host setup

```bash
sudo apt-get update
sudo apt-get install -y python3.11 python3.11-venv nginx
sudo useradd --system --create-home --shell /usr/sbin/nologin quantvn
sudo -u quantvn git clone <repo-url> /home/quantvn/Quant_Finance
sudo -u quantvn python3.11 -m venv /home/quantvn/venv
sudo -u quantvn /home/quantvn/venv/bin/pip install \
    -e /home/quantvn/Quant_Finance/quant-vn-dashboard/apps/api
```

Drop the production `.env` into `/home/quantvn/quant-vn-api.env` (chmod 600,
owner `quantvn`).

### systemd unit — `/etc/systemd/system/quant-vn-api.service`

```ini
[Unit]
Description=Quant VN Dashboard API (FastAPI / uvicorn)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=quantvn
Group=quantvn
WorkingDirectory=/home/quantvn/Quant_Finance/quant-vn-dashboard/apps/api
EnvironmentFile=/home/quantvn/quant-vn-api.env
ExecStart=/home/quantvn/venv/bin/uvicorn main:app \
    --host 127.0.0.1 --port 8000 \
    --proxy-headers --forwarded-allow-ips='*' \
    --timeout-keep-alive 75
Restart=on-failure
RestartSec=5
# Don't kill SSE clients aggressively on shutdown
KillSignal=SIGINT
TimeoutStopSec=30

[Install]
WantedBy=multi-user.target
```

Enable:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now quant-vn-api
sudo systemctl status quant-vn-api
```

### nginx reverse proxy — `/etc/nginx/sites-available/quant-vn-api`

SSE needs buffering OFF and long read timeouts.

```nginx
server {
    listen 443 ssl http2;
    server_name api.example.com;

    ssl_certificate     /etc/letsencrypt/live/api.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/api.example.com/privkey.pem;

    # Default proxy for normal JSON routes
    location / {
        proxy_pass         http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header   Host              $host;
        proxy_set_header   X-Real-IP         $remote_addr;
        proxy_set_header   X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header   X-Forwarded-Proto $scheme;
        proxy_read_timeout 60s;
    }

    # SSE endpoints — disable buffering, long timeouts
    location ~ ^/(stream|live)/ {
        proxy_pass         http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header   Host              $host;
        proxy_set_header   X-Real-IP         $remote_addr;
        proxy_set_header   X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header   X-Forwarded-Proto $scheme;
        proxy_set_header   Connection        '';
        proxy_buffering    off;
        proxy_cache        off;
        chunked_transfer_encoding on;
        proxy_read_timeout 24h;
        proxy_send_timeout 24h;
    }
}

server {
    listen 80;
    server_name api.example.com;
    return 301 https://$host$request_uri;
}
```

Enable and reload:

```bash
sudo ln -s /etc/nginx/sites-available/quant-vn-api /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
```

### Log rotation

journald already rotates `quant-vn-api` logs by size. If you tee uvicorn to a
file, add `/etc/logrotate.d/quant-vn-api`:

```
/var/log/quant-vn-api/*.log {
    daily
    rotate 14
    compress
    delaycompress
    missingok
    notifempty
    copytruncate
}
```

---

## Supabase

1. Create a project at supabase.com. Note the region (pick one close to
   Vietnam — Singapore `ap-southeast-1` is the usual choice).
2. From **Project Settings → API**, copy:
   - `URL` → `SUPABASE_URL` (and `NEXT_PUBLIC_SUPABASE_URL`)
   - `anon public` key → `SUPABASE_ANON_KEY` and `NEXT_PUBLIC_SUPABASE_ANON_KEY`
   - `service_role` key → `SUPABASE_SERVICE_ROLE_KEY` **(API host only)**
3. From **Project Settings → API → JWT Settings**, copy the JWT secret →
   `SUPABASE_JWT_SECRET`.
4. From **Project Settings → Database**, copy the password → `SUPABASE_DB_PASSWORD`
   and build `DATABASE_URL` per `.env.example`.
5. Apply migrations **in this exact order** via SQL Editor or `psql`:

   ```bash
   psql "$DATABASE_URL" -f db/migrations/0001_init.sql
   psql "$DATABASE_URL" -f db/migrations/0002_portfolio_assets.sql
   psql "$DATABASE_URL" -f db/migrations/0003_recommendations_extend.sql
   ```

6. Confirm RLS is **enabled** on every user-owned table (`auth.uid()` policies).

---

## Upstash Redis

Two compatible ways to wire Redis. Pick one and leave the other blank.

**Option A — REST (Upstash-native, works from serverless too):**

```
UPSTASH_REDIS_REST_URL=https://<region>-<id>.upstash.io
UPSTASH_REDIS_REST_TOKEN=<token from Upstash console>
REDIS_URL=
```

**Option B — Plain TCP (use Upstash "Redis URL" or any managed Redis):**

```
REDIS_URL=rediss://default:<password>@<host>:<port>
UPSTASH_REDIS_REST_URL=
UPSTASH_REDIS_REST_TOKEN=
```

If both are blank the API falls back to an in-process LRU cache — fine for
single-instance MVP, **not** acceptable once you scale past one API replica.

---

## SSI FastConnect env setup

SSI credentials live only in the API host's secret manager / `.env`. They
must never be in Cloudflare Pages, the frontend bundle, or git.

```
SSI_CONSUMER_ID=<from SSI iBoard FastConnect portal>
SSI_CONSUMER_SECRET=<from SSI iBoard FastConnect portal>
SSI_BASE_URL=https://fc-data.ssi.com.vn
SSI_TRADING_BASE_URL=https://fc-tradeapi.ssi.com.vn
SSI_USE_MOCK=false
```

For local dev (or CI) without an SSI account, set `SSI_USE_MOCK=true`. The
deterministic mock provider returns the same shape as the real API, so every
route, the poller, and the SSE streams still work end-to-end.

---

## Production environment checklist

Run through this before flipping DNS to a new deployment.

- [ ] All `NEXT_PUBLIC_*` vars set in the **Cloudflare Pages** project
      (`NEXT_PUBLIC_API_BASE_URL`, `NEXT_PUBLIC_SUPABASE_URL`,
      `NEXT_PUBLIC_SUPABASE_ANON_KEY`).
- [ ] `SUPABASE_SERVICE_ROLE_KEY` set on the **API host only** — never in
      Cloudflare Pages and never in the frontend bundle.
- [ ] `SUPABASE_JWT_SECRET` matches the Supabase project's JWT secret exactly
      (`Project Settings → API → JWT Settings`).
- [ ] `SSI_USE_MOCK=false` **and** `SSI_CONSUMER_ID` / `SSI_CONSUMER_SECRET`
      populated — or explicitly `SSI_USE_MOCK=true` if running in mock mode.
- [ ] `CORS_ORIGINS` set to the production frontend URL as a **JSON list**,
      e.g. `["https://app.example.com"]` (pydantic-settings parses JSON; a
      bare string will not work in production).
- [ ] `APP_ENV=production`.
- [ ] Redis reachable from the API host (`redis-cli -u $REDIS_URL ping` or
      `curl $UPSTASH_REDIS_REST_URL/ping -H "Authorization: Bearer $UPSTASH_REDIS_REST_TOKEN"`).
- [ ] Supabase migrations `0001_init.sql`, `0002_portfolio_assets.sql`,
      `0003_recommendations_extend.sql` applied in that order.
- [ ] `GET /system/health` returns `{"status":"ok"}`.
- [ ] `GET /recommendations/symbol/FPT` returns 200 with a payload (real or
      mock — whichever mode you deployed).
- [ ] nginx `/stream/*` and `/live/*` locations have `proxy_buffering off`
      and a long `proxy_read_timeout` (see the nginx snippet above).
- [ ] systemd unit `quant-vn-api` is `enabled` and `active (running)`.

---

## CI

GitHub Actions workflows live at the **workspace root** under
`.github/workflows/` (not under `quant-vn-dashboard/`) because the repo is
rooted at `Quant_Finance/`:

| Workflow             | Triggers                          | What it runs                                                   |
| -------------------- | --------------------------------- | -------------------------------------------------------------- |
| `backend-tests.yml`  | push main / PR / manual           | `pytest` on `apps/api` against Python 3.11 + 3.12, stable suite. A second job runs the known-failing suites with `continue-on-error: true`. |
| `frontend-build.yml` | push main / PR / manual           | `pnpm typecheck`, `pnpm build`, `pnpm test` (vitest) on `apps/web` with Node 20. |
| `lint.yml`           | push main / PR / manual           | `ruff check` on `apps/api`, `eslint` + `prettier --check` on `apps/web`, advisory `mypy`. |

All three use path filters so a frontend-only PR will not run backend tests
and vice versa.

## FastAPI backend on Fly.io (optional alternative to GCP e2-micro)

Fly.io is an acceptable Phase 1 host because the free tier comfortably runs a
small FastAPI process for personal use and its long-lived connections support
SSE without buffering. **Do NOT use a serverless function host** (Cloudflare
Workers, Vercel Edge, Netlify Functions) — SSE needs a persistent connection
the function timeout will kill.

### One-time setup

```bash
# Install the CLI once (https://fly.io/docs/hands-on/install-flyctl/).
brew install flyctl                     # or the curl|sh installer
fly auth login
cd apps/api
fly launch --no-deploy                  # generates fly.toml; pick a region near VN
```

Recommended `fly.toml` deltas after generation:

```toml
# fly.toml
app = "quant-vn-api"                    # globally unique
primary_region = "sin"                  # Singapore — closest to VN

[build]
  dockerfile = "Dockerfile"             # use the existing apps/api/Dockerfile

[env]
  APP_ENV = "production"
  API_HOST = "0.0.0.0"
  API_PORT = "8000"
  SSI_USE_MOCK = "false"
  SSI_BASE_URL = "https://fc-data.ssi.com.vn"

[http_service]
  internal_port = 8000
  force_https = true
  auto_stop_machines = false            # SSE needs a persistent machine
  auto_start_machines = true
  min_machines_running = 1              # keeps SSE consumers alive

  [[http_service.checks]]
    method = "GET"
    path = "/health"
    interval = "30s"
    timeout = "5s"
```

### Secrets

Set every server-only var as a Fly secret — they are mounted as env vars at
boot and never written to the image:

```bash
fly secrets set \
  SUPABASE_URL='https://<project>.supabase.co' \
  SUPABASE_ANON_KEY='<paste>' \
  SUPABASE_SERVICE_ROLE_KEY='<paste>' \
  SUPABASE_JWT_SECRET='<paste>' \
  SUPABASE_DB_PASSWORD='<paste>' \
  DATABASE_URL='postgresql://postgres:<pwd>@db.<project>.supabase.co:5432/postgres' \
  SSI_CONSUMER_ID='<paste>' \
  SSI_CONSUMER_SECRET='<paste>' \
  CORS_ORIGINS='["https://<your-frontend>.pages.dev"]' \
  REDIS_URL='<if using TCP Redis>' \
  UPSTASH_REDIS_REST_URL='<if using Upstash REST>' \
  UPSTASH_REDIS_REST_TOKEN='<if using Upstash REST>'
```

### Deploy + smoke

```bash
fly deploy
fly logs                                # watch boot for missing-secret warnings
curl https://quant-vn-api.fly.dev/health
fly status                              # confirms one machine running, in sin
```

### Rollback

```bash
fly releases                            # list past releases
fly releases revert <release-id>        # one-command rollback
```

### Phase 2 notes

- Upgrade to `dedicated-cpu-1x` if SSE concurrency exceeds ~20 connections.
- Configure Fly's built-in metrics → Grafana before opening to multiple users.
- Trading provider remains **placeholder only**; do not add `/orders` routes.

## Production smoke-test checklist

Run this after every deploy, before declaring the release green. Each item
maps to a concrete command the operator can run from their laptop or shell.

| # | Check | Command / action | Pass criterion |
|---|---|---|---|
| 1 | Backend `/health` returns 200 | `curl https://<api>/health` | `{"status": "ok", "env": "production", "version": "..."}` |
| 2 | Frontend loads | open `https://<frontend>` in browser | login page renders, no JS console errors |
| 3 | Login works | sign in with a real Supabase Auth user | redirected to `/dashboard` |
| 4 | Dashboard loads | watch `/dashboard` | KPI cards visible (data may still be mock) |
| 5 | Market mock data loads | open `/market` | index cards render with prices |
| 6 | System status loads | open `/data-quality` | provider/cache/supabase/duckdb/poller cards render green |
| 7 | No secrets in browser devtools | DevTools → Network → check every XHR | response bodies contain no `sb_secret_…`, no JWT-shape blob in plain text outside the Authorization header, no SSI consumer secret |
| 8 | No frontend direct SSI requests | DevTools → Network filter `ssi.com.vn` | **zero** matching requests; all market data flows via the FastAPI host |

If any item fails:

1. **#1 fails** → check `fly logs` (or systemd journal) for missing secrets or
   import error. Roll back with `fly releases revert <id>` (or the previous
   container tag on the VPS).
2. **#7 fails** (a secret in a response body) → STOP — rotate the leaked
   secret on the issuing provider before any further investigation.
3. **#8 fails** (direct SSI calls from the browser) → the
   `no-direct-ssi.test.ts` CI gate failed open. Block the deploy, find the
   offending file, run `npx vitest run no-direct-ssi` locally.

A passing checklist clears v0.1 for user demo. Tag the release:

```bash
git tag v0.1.0 && git push --tags
```
