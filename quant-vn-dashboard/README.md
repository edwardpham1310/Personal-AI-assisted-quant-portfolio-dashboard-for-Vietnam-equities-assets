# Quant VN Dashboard

Personal AI-assisted quant portfolio dashboard for Vietnam equities. Monorepo
containing a Next.js frontend (`apps/web`) and a FastAPI backend (`apps/api`),
plus shared types in `packages/shared` and local data folders in `data/`.

Phase 1 is **recommend-only**: no live orders are placed from this app.

## Layout

```
quant-vn-dashboard/
├── apps/
│   ├── web/             Next.js 14 (App Router, TS, Tailwind) — public UI
│   └── api/             FastAPI service — the only SSI gateway
├── packages/shared/     Shared TS types/constants for the web app
├── data/                Local DuckDB / parquet / raw / processed (gitignored)
└── docs/                Architecture, API, deployment, assumptions
```

The legacy library packages (`datapipe/`, `quant/`) live one level up in the
workspace and are consumed by `apps/api` once wired in a later step.

## Prerequisites

- Python 3.11+
- Node.js 20+ and pnpm 9+ (or npm/yarn — examples use pnpm)
- (Optional) Docker + docker-compose for local Redis

## Quickstart

```bash
# 1. From quant-vn-dashboard/
cp .env.example .env
# Edit .env — leave secrets empty for the first run; the API will warn but boot.

# 2. Install
make install

# 3. Run (in two terminals)
make dev-api      # http://localhost:8000  (docs at /docs)
make dev-web      # http://localhost:3000
```

See `docs/deployment.md` for production hosting (Cloudflare Pages, GCP e2-micro
or a cheap VPS, Supabase, Upstash).

## Security

- `.env` is gitignored. Never commit secrets.
- SSI credentials live **only** in the API process. The frontend never sees them.
- See `docs/assumptions.md` for the security model and trust boundaries.

## Make targets

| Target          | What it does                                   |
| --------------- | ---------------------------------------------- |
| `make install`  | Install API (pip) and web (pnpm) dependencies. |
| `make dev`      | Print instructions to run api + web.           |
| `make dev-api`  | Start FastAPI with auto-reload on :8000.       |
| `make dev-web`  | Start Next.js dev server on :3000.             |
| `make test`     | Run API + web test suites.                     |
| `make lint`     | Lint both apps.                                |
| `make format`   | Format both apps.                              |
