# Operations Runbook

This runbook covers day-to-day operation of the Quant VN Dashboard MVP:
what to check, what alerts mean, how to restart things, how to rotate
secrets, and which Phase 1 limitations operators must hold in mind. For
host placement of each component see `docs/deployment.md`; for the full
list of configurable variables see `docs/environment-variables.md`.

## Daily ops checklist

Run at the start of each session before trusting any number in the UI.

- [ ] Open `/data-quality` in the web app and scan for unresolved issues.
- [ ] Hit `GET /health` on the API — must return `200` with `status: "ok"`.
- [ ] Hit `GET /system/status` — confirm `missing_secrets` is empty and
      `redis_configured` is `true` in production.
- [ ] Hit `GET /market/live/status` — confirm `poller_enabled` matches
      intent, `poller_running` is `true` when enabled, and `last_poll` is
      within the configured `MARKET_POLL_INTERVAL_SECONDS` window.
- [ ] Spot-check `GET /scanner/universe?vn30=true` — must return `200`
      with a non-empty list during market hours.
- [ ] Confirm the count of quotes carrying `"stale": true` in
      `GET /market/live/quotes?symbols=FPT,MWG,HPG,VNM,VCB,VRE` is below
      the operator threshold (typical: zero during market hours, all-stale
      after close is expected).

## Common alerts

| Symptom | Likely cause | First fix |
| --- | --- | --- |
| `GET /health` returns 5xx | Process crashed or container OOM | `docker compose logs api`, then restart (see below). |
| `GET /system/status` shows `missing_secrets` non-empty | Secret missing from API host env | Add the secret to the host secret manager and restart the API. |
| `GET /market/live/status` returns `poller_enabled=true, poller_running=false` | Poller crashed during startup | Check logs for `market_poller.disabled` or provider errors; restart API. |
| `GET /market/status` returns `ready=false` | SSI auth failed or upstream outage | Verify `SSI_CONSUMER_ID` / `SSI_CONSUMER_SECRET`; check SSI status page. |
| High stale-quote count (`stale=true`) during market hours | Poller paused, Redis unreachable, or SSI throttling | Inspect `last_poll` timestamp; check Redis connectivity; review SSI rate-limit headers in logs. |
| Frontend shows 401 errors on every page | Supabase JWT secret rotated without updating API | Update `SUPABASE_JWT_SECRET` on the API host, restart, and have users re-login. |
| Frontend shows 503 on portfolio/recommendation routes | Required secret missing in `development`/`staging` | See `GET /system/status` `missing_secrets`. |
| CORS error in browser console | `CORS_ORIGINS` does not include the Pages URL | Update the env var (JSON array form preferred), restart API. |
| `GET /scanner/universe?vn30=true` returns 400 | Caller forgot `vn30=true` query param | This is by design — Phase 1 only scans VN30 in `/universe`. |

## Common debug commands

```bash
# Liveness and config snapshot
curl -s http://localhost:8000/health | jq
curl -s http://localhost:8000/system/status | jq

# Provider + poller health (auth required in real deploys)
curl -s -H "Authorization: Bearer $JWT" \
  http://localhost:8000/market/status | jq
curl -s -H "Authorization: Bearer $JWT" \
  http://localhost:8000/market/live/status | jq

# Hot-cache quote sanity check
curl -s -H "Authorization: Bearer $JWT" \
  'http://localhost:8000/market/live/quotes?symbols=FPT,MWG,HPG' | jq

# Logs
docker compose logs -f api          # if running via docker-compose
journalctl -u quant-vn-api -f       # if running under systemd
```

For local dev without docker:

```bash
make dev-api          # FastAPI on :8000
make dev-web          # Next.js on :3000
make test-api         # full API test suite
```

## Standard incident response

1. **Acknowledge** — note the alert source, timestamp, and the failing
   endpoint or page.
2. **Capture state before touching anything**:
   ```bash
   curl -s http://localhost:8000/health > /tmp/health.json
   curl -s http://localhost:8000/system/status > /tmp/status.json
   docker compose logs --since 30m api > /tmp/api-logs.txt
   ```
3. **Triage**:
   - If `/health` is down → restart the API (see below) and keep the log.
   - If `/health` is up but a single route is failing → check
     `/system/status` and the route's owning module (see ownership table).
   - If SSI is the root cause → set `SSI_USE_MOCK=true` only in dev; in
     production wait for SSI and surface a banner in the UI.
4. **Mitigate** — apply the smallest reversible change.
5. **Postmortem** — file a note in the workspace audit folder
   (`quant/docs/audit/` or a dashboard equivalent once it exists).

Ownership map for fast triage:

| Failing route prefix | Owner module |
| --- | --- |
| `/health`, `/system/*` | `api/routes/health.py`, `api/routes/system.py` |
| `/market/*`, `/stream/*` | `api/routes/market.py`, `workers/market_poller.py` |
| `/portfolio/*`, `/assets/*` | `api/routes/portfolio.py`, `services/portfolio_valuation.py` |
| `/recommendations/*`, `/scanner/*` | `api/routes/recommendations.py`, `services/risk_guardrails.py` |
| `/auth/*`, `/settings/*`, `/watchlists/*` | Supabase + corresponding route files |

## Restart procedures

### API under systemd

```bash
sudo systemctl restart quant-vn-api
sudo systemctl status  quant-vn-api
journalctl -u quant-vn-api -n 100 --no-pager
```

### API under docker-compose

```bash
cd /opt/quant-vn-dashboard
docker compose --profile api restart api
docker compose logs --tail 100 api
```

### Redis container (local dev / single-host prod)

```bash
docker compose restart redis
docker compose exec redis redis-cli ping     # expects PONG
```

Restarting Redis loses the hot cache. The poller will refill the
configured `MARKET_CORE_SYMBOLS` and `MARKET_CORE_INDICES` within
one `MARKET_POLL_INTERVAL_SECONDS` window. Active SSE subscribers will
re-subscribe on next request.

### Cloudflare Pages redeploy

1. Open the Pages project → Deployments.
2. Either retry the latest deployment or pick a known-good prior
   deployment and click "Rollback".
3. Verify the live URL serves the expected build hash and that the
   browser can reach `NEXT_PUBLIC_API_BASE_URL`.

## Migration upgrade procedure

Current migrations live under `db/migrations/`: `0001_init.sql`,
`0002_portfolio_assets.sql`, `0003_recommendations_extend.sql`. When the
next migration (`0004_*.sql`) lands, follow this procedure:

1. **Read the migration end-to-end** and confirm whether it is
   forward-only or includes a rollback section.
2. **Dry-run on staging**: apply via
   `supabase db execute --file db/migrations/0004_*.sql` against the
   staging project. Run the API test suite (`make test-api`) and the
   smoke checks in the daily checklist.
3. **Take a manual snapshot** of the production project: Supabase
   Dashboard → Database → Backups → Create. Supabase PITR is on by
   default but a deliberate snapshot makes the rollback point obvious.
4. **Announce a brief window** in case the migration takes a write lock.
5. **Apply to production** via the Supabase Dashboard SQL Editor or
   `supabase db push`. Watch for errors.
6. **Verify**:
   - `curl /health` returns 200.
   - `curl /system/status` shows no new missing secrets.
   - Run the daily checklist above end-to-end.
7. If anything looks wrong, restore from the snapshot taken in step 3.

## Secret rotation playbook

All rotations follow the same shape: regenerate at the source → update the
**API host's** secret manager → restart the API → verify. Never put any of
these in Cloudflare Pages.

### SSI consumer secret

1. Log into SSI FastConnect portal → rotate consumer secret.
2. Set the new value in the API host env: `SSI_CONSUMER_SECRET=...`.
3. Restart the API (see Restart procedures).
4. Verify `GET /market/status` returns `ready=true`.

### Supabase JWT secret

1. Supabase Dashboard → Project Settings → API → Rotate JWT secret.
2. Update `SUPABASE_JWT_SECRET` on the API host.
3. Restart the API.
4. All existing user sessions become invalid; users must sign in again.
   Communicate the forced re-login before rotating during business hours.

### Supabase service-role key

1. Supabase Dashboard → Project Settings → API → Regenerate service-role.
2. Update `SUPABASE_SERVICE_ROLE_KEY` on the API host.
3. Restart the API.
4. Verify any trusted-job path that bypasses RLS still works (in MVP
   this is limited; covered by the API test suite).

### Upstash Redis REST token

1. Upstash Console → database → Regenerate REST token.
2. Update `UPSTASH_REDIS_REST_TOKEN` (and `UPSTASH_REDIS_REST_URL` if it
   moved) on the API host.
3. Restart the API.
4. Verify `GET /market/live/status` returns a non-`unknown` `cache_backend`.

## Backup and restore

### Supabase Postgres

- Point-in-time recovery is built into Supabase and on by default.
  Confirm retention period matches your RPO.
- Before any migration or risky change, take a manual snapshot:
  Database → Backups → Create.
- Restore via the Supabase Dashboard. The DSN does not change after
  restore, so the API needs no re-config.

### Upstash Redis

- This is a cache only — every key is reconstructable from SSI plus
  the configured `MARKET_CORE_SYMBOLS` / `MARKET_CORE_INDICES`.
- Acceptable to lose. The impact is a single-cycle cold start (~ one
  `MARKET_POLL_INTERVAL_SECONDS` window) and a temporary spike in SSI
  request volume.

### DuckDB / Parquet (local analytics)

- Lives on the API host disk under `DUCKDB_PATH` and `PARQUET_DATA_DIR`.
- Re-ingest from the `datapipe/` package; the upstream provider is the
  source of truth.
- No need to back up to S3 in MVP.

## Phase 1 known limitations operators must know

These are by design or documented bugs — do not treat as incidents.

- **`CORS_ORIGINS` JSON-vs-CSV behaviour.** `pydantic-settings` prefers
  JSON. We added a CSV fallback validator, but a few callers and the
  `apps/api/tests/conftest.py` fixture historically set the bare CSV
  form, which the JSON branch rejects. Use the JSON-array form in
  production env to avoid the corner case.
- **Pre-existing test suite has CORS env parsing failures.** Some tests
  in `apps/api/tests/` set `CORS_ORIGINS` as a bare CSV string and rely
  on per-test monkeypatching to flip it to JSON. Treat the known-failing
  cases as such and do not block deploys on them; the production code
  path is unaffected. *Verify the exact failing tests with the team
  before suppressing in CI.*
- **Realized PnL is gross of fees.** `services/portfolio_valuation.py`
  computes realized PnL as `sell_qty * (price - running_avg_cost)`. SSI
  brokerage fees, VAT, taxes, and cash-advance interest are **not**
  subtracted. Users must apply the cost model from `quant/` separately
  for any post-tax/post-fee view.
- **No FIFO / LIFO lot tracking.** Realized PnL uses a single weighted-
  average running cost per `(account_id, symbol)`. Tax-lot reporting is
  not available; do not export these numbers as a tax document.
- **Ceiling/floor prices not provided in Phase 1.** SSI does not reliably
  expose daily ceiling/floor. The recommendation guardrail
  `check_ceiling_floor` in `services/risk_guardrails.py` emits an `INFO`
  hit (`ceiling_floor_unavailable`) instead of blocking; this is
  intentional and not an alert.
- **Recommend-only.** The dashboard never places orders. Any UI element
  suggesting "execute" is a future-phase placeholder.
- **In-memory cache fallback.** If neither `REDIS_URL` nor the Upstash
  vars are set, the API uses a per-process in-memory cache. Acceptable
  for local dev only; never run production without Redis.
- **Market poller off by default.** `ENABLE_MARKET_POLLER=false` is the
  default. Live cache routes return empty arrays until the poller is
  enabled. This protects SSI quota during onboarding and tests.

## See also

- `docs/environment-variables.md` — full variable reference.
- `docs/deployment.md` — host placement and CI/CD model.
- `docs/assumptions.md` — Vietnam market mechanics the system depends on.
- `db/README.md` — migration application procedures.
