# Security Checklist — Quant VN Dashboard MVP (Phase 1)

Audit date: 2026-05-30
Auditor: Security Engineer (read-only review, no code changes)
Scope: Phase 1 = recommend-only research dashboard. No order placement. No
real broker write APIs are wired.

---

## 1. Threat Model

### Assets
- User authentication tokens (Supabase JWT, HS256)
- Supabase service-role key (Postgres god-mode; must never leave the API host)
- SSI FastConnect consumer ID / secret (data licence; rate-limited; not a
  trading credential in Phase 1)
- User-owned data: watchlists, manual positions, cash balances, trade
  ledger, recommendation snapshots, user settings
- Licensed market data (quotes, OHLCV, indices) — leakage is a licence breach
  even though it isn't PII

### Attackers
- Anonymous internet (probes `/system/health`, `/health`, login flow)
- Authenticated user A trying to read user B's portfolio (cross-tenant)
- Compromised browser session (XSS would leak the anon-key session cookie,
  not the service-role key)
- Supply-chain (a compromised npm/pypi dep running in the browser or API)

### Trust boundaries
```
Browser  ──(HTTPS, anon-key cookie session)──►  Next.js (CF Pages, Node runtime)
   │                                              │
   │                                              ├─► Supabase (anon key + user JWT, RLS-enforced)
   │                                              │
   └─(EventSource same-origin)──► Next.js BFF ───►  FastAPI (Bearer JWT)
                                                    │
                                                    ├─► Supabase PostgREST (user JWT, RLS)
                                                    ├─► SSI FastConnect (server-only consumer creds)
                                                    └─► Redis / Upstash (server-only)
```
The browser never sees the SSI credential, the Supabase service-role key,
the Supabase JWT signing secret, or the Redis URL.

---

## 2. Pre-deploy Checklist (tick before `APP_ENV=production`)

- [ ] `.env` is not committed: `git check-ignore .env` returns `IGNORED`,
      `git ls-files | grep -E '(^|/)\.env$'` is empty (verified: PASS)
- [ ] `SUPABASE_SERVICE_ROLE_KEY` is set **only** on the API host
      (Cloudflare Worker secret / VPS env). Never in Pages build env.
- [ ] `SSI_CONSUMER_ID` and `SSI_CONSUMER_SECRET` are set **only** on the
      API host. Frontend has no awareness of these names.
- [ ] `CORS_ORIGINS` = production frontend URL (comma-separated or JSON
      list). NEVER `*`. Example: `CORS_ORIGINS=https://dashboard.example.com`
- [ ] `SUPABASE_JWT_SECRET` matches the Supabase project JWT secret used
      to sign sessions (Settings → API → JWT Settings).
- [ ] Migrations `0001`, `0002`, `0003` applied to the prod Supabase
      project (`select * from supabase_migrations.schema_migrations`).
- [ ] In the Supabase dashboard, RLS is **enabled** on every table listed
      in §4 (Per-area findings → RLS).
- [ ] All routes audited for `Depends(get_current_user)` — see auth table
      in §3.
- [ ] No secret in logs: run
      `grep -iE '(eyJ|bearer |sk-|consumerSecret|service_role|jwt_secret|password=)' app.log`
      and confirm 0 hits over a 24h sample.
- [ ] `ENABLE_MARKET_POLLER=true` (otherwise live data won't backfill the
      cache). The poller never logs secrets (verified).
- [ ] `SSI_USE_MOCK=false` in prod.
- [ ] `LOG_LEVEL=INFO` (not `DEBUG`, which can include third-party traces).
- [ ] `REDIS_URL` uses TLS (`rediss://`) when crossing the network.
- [ ] HTTPS terminated upstream (Cloudflare). API never serves cleartext.

---

## 3. Auth coverage by route

Every route is in this table — Phase 1 expects auth on everything except
the two liveness probes.

| Method+Path                                | File:line                                                     | Auth dep | Status |
|--------------------------------------------|---------------------------------------------------------------|----------|--------|
| GET  `/health`                             | apps/api/src/api/routes/health.py:12                          | none     | ok (public liveness) |
| GET  `/system/health`                      | apps/api/src/api/routes/system.py:59                          | none     | ok (public liveness) |
| GET  `/system/status`                      | apps/api/src/api/routes/system.py:109                         | yes      | ok |
| GET  `/system/providers`                   | apps/api/src/api/routes/system.py:145                         | yes      | ok |
| GET  `/system/cache`                       | apps/api/src/api/routes/system.py:158                         | yes      | ok |
| GET  `/system/data-quality`                | apps/api/src/api/routes/system.py:172                         | yes      | ok |
| GET  `/auth/me`                            | apps/api/src/api/routes/auth.py:13                            | yes      | ok |
| GET  `/settings`                           | apps/api/src/api/routes/settings.py:19                        | yes      | ok |
| PUT  `/settings`                           | apps/api/src/api/routes/settings.py:42                        | yes      | ok |
| GET  `/watchlists`                         | apps/api/src/api/routes/watchlist.py:21                       | yes      | ok |
| POST `/watchlists`                         | apps/api/src/api/routes/watchlist.py:46                       | yes      | ok |
| POST `/watchlists/{id}/items`              | apps/api/src/api/routes/watchlist.py:70                       | yes      | ok |
| DELETE `/watchlists/{id}/items/{item_id}`  | apps/api/src/api/routes/watchlist.py:107                      | yes      | ok |
| GET  `/market/securities`                  | apps/api/src/api/routes/market.py:90                          | yes      | ok |
| GET  `/market/securities/{symbol}`         | apps/api/src/api/routes/market.py:105                         | yes      | ok |
| GET  `/market/indices`                     | apps/api/src/api/routes/market.py:118                         | yes      | ok |
| GET  `/market/index-components/{code}`     | apps/api/src/api/routes/market.py:134                         | yes      | ok |
| GET  `/market/ohlcv/daily/{symbol}`        | apps/api/src/api/routes/market.py:151                         | yes      | ok |
| GET  `/market/ohlcv/intraday/{symbol}`     | apps/api/src/api/routes/market.py:171                         | yes      | ok |
| GET  `/market/quotes`                      | apps/api/src/api/routes/market.py:194                         | yes      | ok |
| GET  `/market/status`                      | apps/api/src/api/routes/market.py:218                         | yes      | ok |
| GET  `/market/live/quotes`                 | apps/api/src/api/routes/market.py:236                         | yes      | ok |
| GET  `/market/live/indices`                | apps/api/src/api/routes/market.py:259                         | yes      | ok |
| GET  `/market/live/status`                 | apps/api/src/api/routes/market.py:272                         | yes      | ok |
| GET  `/stream/heartbeat`                   | apps/api/src/api/routes/stream.py:107                         | none     | warn (intentional liveness; emits only timestamps) |
| GET  `/stream/quotes`                      | apps/api/src/api/routes/stream.py:123                         | yes      | ok |
| GET  `/stream/watchlist/{id}`              | apps/api/src/api/routes/stream.py:138                         | yes      | ok |
| GET  `/stream/market-overview`             | apps/api/src/api/routes/stream.py:184                         | yes      | ok |
| GET  `/portfolio/manual`                   | apps/api/src/api/routes/portfolio.py:85                       | yes      | ok |
| POST `/portfolio/manual/accounts`          | apps/api/src/api/routes/portfolio.py:116                      | yes      | ok |
| POST `/portfolio/manual/positions`         | apps/api/src/api/routes/portfolio.py:140                      | yes      | ok |
| PUT  `/portfolio/manual/positions/{id}`    | apps/api/src/api/routes/portfolio.py:178                      | yes      | ok |
| DELETE `/portfolio/manual/positions/{id}`  | apps/api/src/api/routes/portfolio.py:209                      | yes      | ok |
| GET  `/portfolio/summary`                  | apps/api/src/api/routes/portfolio.py:245                      | yes      | ok |
| GET  `/portfolio/positions`                | apps/api/src/api/routes/portfolio.py:267                      | yes      | ok |
| POST `/portfolio/positions`                | apps/api/src/api/routes/portfolio.py:290                      | yes      | ok |
| PUT  `/portfolio/positions/{id}`           | apps/api/src/api/routes/portfolio.py:326                      | yes      | ok |
| DELETE `/portfolio/positions/{id}`         | apps/api/src/api/routes/portfolio.py:357                      | yes      | ok |
| POST `/portfolio/sync/ssi`                 | apps/api/src/api/routes/portfolio.py:378                      | yes      | ok — returns 501 placeholder |
| GET  `/assets/summary`                     | apps/api/src/api/routes/assets.py:120                         | yes      | ok |
| GET  `/assets/pnl`                         | apps/api/src/api/routes/assets.py:167                         | yes      | ok |
| GET  `/assets/costs`                       | apps/api/src/api/routes/assets.py:243                         | yes      | ok |
| GET  `/recommendations`                    | apps/api/src/api/routes/recommendations.py:462                | none     | warn (legacy placeholder; returns no data) |
| GET  `/recommendations/symbol/{symbol}`    | apps/api/src/api/routes/recommendations.py:335                | yes      | ok |
| GET  `/recommendations/watchlist/{id}`     | apps/api/src/api/routes/recommendations.py:378                | yes      | ok |
| POST `/recommendations/preview`            | apps/api/src/api/routes/recommendations.py:422                | yes      | ok |
| GET  `/scanner/symbol/{symbol}`            | apps/api/src/api/routes/scanner.py:135                        | yes      | ok |
| GET  `/scanner/watchlist/{id}`             | apps/api/src/api/routes/scanner.py:159                        | yes      | ok |
| GET  `/scanner/universe`                   | apps/api/src/api/routes/scanner.py:192                        | yes      | ok |

Verdict: every user/data route enforces `Depends(get_current_user)`.
Only intentional public endpoints are `/health`, `/system/health`,
`/stream/heartbeat`, and the legacy `/recommendations` placeholder.

---

## 4. Per-area findings

### 4.1 Secrets handling
- ok — `apps/api/src/core/config.py:105-133`: `missing_secrets()` and
  `warn_if_missing_secrets()` raise `RuntimeError` when `APP_ENV=production`
  is missing any of `supabase_url`, `supabase_jwt_secret`,
  `supabase_service_role_key`, `database_url`, `ssi_consumer_id`,
  `ssi_consumer_secret`. Lifespan calls it on startup (main.py:40).
- ok — `apps/api/src/providers/market_data/ssi_fastconnect.py:119,135`:
  only the exception class name and `expiresIn` are logged.
  `_refresh_token_locked` uses `raise … from None` to drop the chained
  exception so the consumerSecret payload is not embedded in tracebacks.
- ok — `apps/api/src/services/cache.py:142`: Redis error logs the
  exception type only, never the URL.
- ok — `apps/api/src/services/data_quality.py:37-58`: `_redact()` strips
  `Bearer …`, JWT-shaped (`eyJ…`), and `key=value` pairs for
  `api_key|secret|password|token|authorization|jwt|consumer_secret`
  before any upstream error string is returned to the route layer.
- ok — `.env.example` documents every variable; secret slots are blank.
- ok — `.gitignore`: `.env`, `.env.*`, `!.env.example` at repo root.
  `git check-ignore .env` returned `IGNORED`; `git ls-files` shows no
  tracked `.env`.
- warn — `.env` is present locally and contains real values. This is
  expected for dev but worth one final operator sanity check before
  cutting to prod (i.e. confirm CI build environments don't bake it in).
- ok — no `logger.*` or `print(` call in `apps/api/src` includes the
  substrings `settings.supabase_*`, `settings.ssi_consumer_*`,
  `settings.*password`, `settings.*token`, or `settings.*secret`
  (verified via grep).

### 4.2 Service-role isolation
- ok — `grep -rn 'SUPABASE_SERVICE_ROLE_KEY\|service_role\|SERVICE_ROLE'
  apps/web/src/` returned 0 hits.
- ok — `apps/web/src/lib/supabase/client.ts:9`,
  `server.ts:13`, `middleware.ts:16` all use `env.supabaseAnonKey`.
  `apps/web/src/lib/env.ts:6-9` only exposes `NEXT_PUBLIC_*`.
- ok — `apps/web/src/no-direct-ssi.test.ts` walks
  `src/app|components|hooks|lib` and fails the build on
  `fc-data.ssi.com.vn`, `fc-tradeapi.ssi.com.vn`, `SSI_CONSUMER_`,
  `consumerSecret`. The guard is still in place.
- ok — `apps/api/src/core/deps.py:18-27`: `get_db()` constructs
  `PostgrestDB` with **anon key only**. Every CRUD path uses the
  caller's `user_jwt` (`apps/api/src/services/supabase_db.py:73-81`),
  so RLS does the actual authorization. The service-role key is loaded
  into `Settings` but never used at runtime — see P1 finding below.

### 4.3 CORS
- warn — `apps/api/src/core/config.py:42`: default
  `cors_origins=["http://localhost:3000"]`. There is no fail-fast when
  `APP_ENV=production` and the operator forgets to override it. A typo
  in deploy config would silently keep the localhost origin (harmless
  but the API would refuse every prod browser request).
- warn — `apps/api/src/main.py:93-99`: `allow_origins` is passed straight
  through. There is no check that `*` is rejected in production. With
  `allow_credentials=True`, browsers will not actually honour `*`, but
  the code should still fail loud rather than relying on browser policy.
- ok — `_split_cors` validator turns a CSV env var into a list cleanly.

### 4.4 Auth coverage
- ok — see §3.
- ok — `auth.py`, `watchlist.py`, `portfolio.py`, `assets.py`,
  `settings.py`, `recommendations.py`, `scanner.py`, `market.py`,
  `stream.py`, `system.py` all import `get_current_user` and use it on
  every user/data route.
- ok — `POST /portfolio/sync/ssi` returns 501 with a placeholder body and
  no real broker call (`portfolio.py:378-385`). It still requires auth.

### 4.5 RLS
| Table                          | RLS enabled (file:line)            | Owner policy            | Notes |
|--------------------------------|------------------------------------|-------------------------|-------|
| profiles                       | 0001_init.sql:196                  | `id = auth.uid()`       | select/insert/update only |
| user_settings                  | 0001_init.sql:197                  | `user_id = auth.uid()`  | FOR ALL |
| watchlists                     | 0001_init.sql:198                  | `user_id = auth.uid()`  | FOR ALL |
| watchlist_items                | 0001_init.sql:199                  | EXISTS via parent       | FOR ALL — parent-owned |
| manual_portfolio_accounts      | 0001_init.sql:200                  | `user_id = auth.uid()`  | FOR ALL |
| manual_positions               | 0001_init.sql:201                  | EXISTS via parent       | FOR ALL — parent-owned |
| recommendation_snapshots       | 0001_init.sql:202                  | select+update only      | INSERT requires service_role; see P1 |
| security_audit_logs            | 0001_init.sql:203                  | select only             | writes via service_role |
| cash_balances                  | 0002_portfolio_assets.sql:75       | EXISTS via parent       | FOR ALL — parent-owned |
| trade_transactions             | 0002_portfolio_assets.sql:76       | EXISTS via parent       | FOR ALL — parent-owned |

0003 only loosens CHECK constraints and adds nullable columns — no
policy regression.

### 4.6 JWT
- ok — `apps/api/src/core/security.py:33-65`: `verify_supabase_jwt`
  validates HS256 signature, audience `authenticated`, expiry (via
  `jose.jwt.decode` default), and asserts `sub` is present.
  503 when secret unconfigured, 401 on bad token. No "skip verification"
  flag exists. The `get_current_user` dependency drops to 401 when the
  `Authorization` header is missing.

### 4.7 Input validation
- ok — `apps/api/src/api/routes/market.py:30` (`SYMBOL_RE`),
  `recommendations.py:56`, `scanner.py:48`, `stream.py:45` all
  enforce `^[A-Z0-9_]{1,20}$` after uppercasing.
- ok — `MAX_QUOTE_SYMBOLS=50` (`market.py:25`), `SSE_MAX_SYMBOLS=50`
  (`stream.py:44`), `MAX_DAILY_HISTORY_DAYS=365`,
  `MAX_INTRADAY_DAYS=30` — DoS guards.
- ok — `SCAN_CONCURRENCY = 5` semaphore in `scanner.py:117` and
  `recommendations.py:305` — caps SSI fan-out.
- warn — `apps/api/src/schemas/portfolio.py:30,39,77,86` and
  `schemas/watchlist.py:27` only enforce `min_length=1, max_length=20`
  on the `symbol` field. The route layer `.upper()`s the value but does
  not validate the character set, so a watchlist or position can be
  written with `'$'` or non-ASCII. Low impact (PostgREST will store the
  string verbatim), but inconsistent with `_SYMBOL_RE` elsewhere.

### 4.8 Dependency posture (current versions)
API (`apps/api/pyproject.toml`):
- `fastapi>=0.115` — recent, no known critical CVEs at the floor.
- `pydantic>=2.7`, `pydantic-settings>=2.4` — current.
- `httpx>=0.27` — current.
- `python-jose[cryptography]>=3.3` — historical issues with `algorithms`
  defaults. This codebase always passes `algorithms=[_HS256]` explicitly
  (`security.py:49`), so the `alg=none` class of bug doesn't apply.
- `redis>=5.0`, `anyio>=4.4`, `uvicorn[standard]>=0.30` — current.

Web (`apps/web/package.json`):
- `next ^15.0.3` — there are known Next 15.x advisories around middleware
  authorisation bypass; pin to the latest 15.x patch on deploy.
- `@supabase/ssr ^0.5.1`, `@supabase/supabase-js ^2.45.1` — current.
- `recharts ^2.13.0`, `react ^18.3.1` — current.

Light pass only — run `pip audit` and `pnpm audit` once before deploy.

---

## 5. Top issues to fix before production

| Prio | Issue                                                                                          | Remediation (one line)                                                                          |
|------|------------------------------------------------------------------------------------------------|-------------------------------------------------------------------------------------------------|
| P0   | CORS has no fail-fast in production when `cors_origins` is default or `*`                      | In `Settings.warn_if_missing_secrets()` or a new validator, raise when `is_production and (cors_origins == ["http://localhost:3000"] or "*" in cors_origins)`. |
| P1   | `recommendation_snapshots` INSERT silently fails — no RLS INSERT policy + route uses user JWT  | Either add `create policy reco_insert … with check (user_id = auth.uid())` (recommended) or switch `_persist_snapshot` to a service-role client. Today every persist throws and is swallowed at `recommendations.py:288`. |
| P1   | `services/supabase_db.py:104` raises `PostgrestError(detail=response.text)` — upstream error body bubbles up via `HTTPException` detail (assets.py / settings.py do not catch it). PostgREST may echo column names / constraint messages | Wrap `PostgrestError` at the route layer, log `type(exc).__name__` only, return a generic 502 detail. |
| P2   | Watchlist / portfolio symbol fields accept any 1-20 char string                                | Add a `field_validator` enforcing `^[A-Z0-9_]{1,20}$` in `schemas/watchlist.py` and `schemas/portfolio.py`, then drop the `.upper()` calls in the routes. |
| P2   | `Settings.supabase_service_role_key` is required at startup but never used by app code         | Either wire it for `_persist_snapshot` and `security_audit_logs` writes, or drop the required-secret entry so deploys don't fake the value. |
| P2   | `/stream/heartbeat` is unauthenticated                                                         | Acceptable today (only emits server timestamps), but document it explicitly so it doesn't drift. |
| P2   | No rate limiting on auth-gated endpoints                                                       | Add per-user IP throttling (Cloudflare WAF rule or a FastAPI middleware) before scaling beyond MVP. |
| P3   | Symbol normalization duplicated across `market.py`, `scanner.py`, `recommendations.py`, `stream.py` | Extract to `core/validators.py` so one regex change covers every route. |

---

## 6. Runtime ops

### Log scanning (run on every host every day in cron)
```bash
# Should report zero matches. If non-zero, rotate the affected secret.
grep -iE '(eyJ[A-Za-z0-9._-]{10,}|bearer [A-Za-z0-9._-]{10,}|sk-[A-Za-z0-9]{8,}|consumerSecret|SUPABASE_SERVICE_ROLE_KEY|jwt_secret)' /var/log/quant-vn-api/*.log
```

### Secret rotation cadence
- Supabase JWT secret: every 6 months, or immediately after a developer
  with access leaves. Procedure: rotate in Supabase dashboard, update
  `SUPABASE_JWT_SECRET` on the API host, restart. All existing sessions
  invalidate (users re-login).
- SSI consumer credentials: every 12 months and on any suspected leak.
  Procedure: request new pair from SSI, swap in `.env`, restart. SSI
  token cache (`SSIFastConnectProvider._token`) drops on process restart
  with no explicit purge needed.
- Supabase anon key: rotate only if leaked in a way that affects the
  attack surface; the anon key is public by design.
- Supabase service-role key: every 6 months, or on suspected leak.
  Lives only on the API host.

### SSI token rotation
The provider auto-refreshes when the cached token is within 60s of
expiry (`ssi_fastconnect.py:_TOKEN_LEEWAY_SECONDS = 60`). On 401 from
SSI, the next call refreshes. To force a refresh, restart the API.

---

## 7. Phase 2 / Phase 3 must-haves (before unlocking SSI Trading)

Phase 1 has no order flow, so the threat model above is narrow. Adding
trading capability changes the risk profile fundamentally — the
following are non-negotiable before any sandbox SSI Trading wiring:

1. Dedicated trading-token store (server-side encrypted, per-user, scoped
   to the Trading API). Never reuse the data-API consumer credential.
2. Per-request 2FA / PIN re-check for any SELL or BUY mutation.
3. Idempotency keys on every order endpoint. Replay protection.
4. Append-only `orders` and `executions` tables (RLS owner-only read).
5. Trading kill-switch (env var + remote flag) wired into the API
   lifespan; flipping it disables every order route immediately.
6. Per-user daily notional + per-symbol position caps enforced in code
   *and* in a Postgres CHECK / trigger.
7. WebAuthn or TOTP enrollment requirement before the trading routes
   unlock for a user.
8. Anomaly logging: every BUY/SELL writes to `security_audit_logs` with
   user_id, IP, user agent, idempotency key, params.
9. CSP + COOP + HSTS headers added to the dashboard. Phase 1 doesn't
   need them; trading does.
10. External pen-test of the trading paths and order-state machine
    before any non-paper traffic.
