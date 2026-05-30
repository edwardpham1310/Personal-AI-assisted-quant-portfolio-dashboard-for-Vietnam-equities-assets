# Architecture

```
┌──────────────────┐    HTTPS / SSE     ┌──────────────────────┐
│  apps/web        │  ───────────────▶  │  apps/api (FastAPI)  │
│  Next.js + Plotly│                    │  Sole SSI gateway    │
│  Supabase JS     │   Supabase JWT     │  Supabase JWT verify │
└──────────────────┘                    └──────┬──────┬────────┘
        │                                      │      │
        │ Supabase Auth                        │      │
        ▼                                      ▼      ▼
   Supabase Auth                       Upstash      SSI FastConnect
                                       Redis        (Data + Trading R/O)
                                          │
                                          ▼
                                  Supabase Postgres
                                  (app data + RLS)
                                          │
                                          ▼
                                  DuckDB / Parquet
                                  (historical analytics)
```

## Trust boundaries

- **Browser** holds only the Supabase session and `NEXT_PUBLIC_*` env vars.
- **`apps/api`** holds every secret: `SSI_*`, `SUPABASE_SERVICE_ROLE_KEY`,
  `SUPABASE_JWT_SECRET`, Redis credentials.
- **Frontend never calls SSI directly**. The API is the only outbound client.

## MVP stack

| Layer | Technology |
| ----- | ---------- |
| Frontend | Next.js + Plotly.js |
| Backend | FastAPI |
| Auth | Supabase Auth |
| App DB | Supabase Postgres |
| Realtime cache | Upstash Redis |
| Market data | SSI FastConnect Data |
| Historical analytics | DuckDB + Parquet |
| Streaming | FastAPI SSE |
| Deployment target | Cloudflare Pages + GCP e2-micro or cheap VPS |

## Module map (MVP)

| Module               | Backend route prefix       | Status         |
| -------------------- | -------------------------- | -------------- |
| Auth                 | `/auth`                    | scaffold       |
| Market data          | `/market`                  | scaffold       |
| Realtime stream      | `/stream`                  | scaffold (SSE) |
| Portfolio            | `/portfolio`               | scaffold       |
| Recommendations      | `/recommendations`         | scaffold       |
| Data quality, system | `/system`                  | scaffold       |
| Health               | `/health`                  | done           |

## Data stores

- **Supabase Postgres** — users, settings, watchlists, portfolios, holdings,
  transactions, recommendations, system events. RLS on every table.
- **Upstash Redis** — hot quote cache, last-known-good, SSE pub/sub channels,
  rate limit counters.
- **DuckDB / Parquet** (local `data/`) — historical OHLCV + indicators +
  liquidity. Read-only from the API.

Tick / quote streams are **not** persisted to Postgres.

## See also

- `docs/api.md` — endpoint surface
- `docs/deployment.md` — hosting model
- `docs/assumptions.md` — what this project assumes about the Vietnam market
- Workspace-level `../../docs/` — product vision, trading rules
