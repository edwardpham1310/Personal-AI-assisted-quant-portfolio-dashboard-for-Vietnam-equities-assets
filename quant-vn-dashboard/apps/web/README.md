# apps/web

Next.js 15 (App Router) frontend for the Quant VN Dashboard.

## Install

```bash
pnpm install
```

## Run (dev)

```bash
pnpm dev
# Open http://localhost:3000 — redirects to /dashboard.
```

`NEXT_PUBLIC_API_BASE_URL` from the monorepo `.env` is used to talk to the
FastAPI service. When set, the dev server also proxies `/api/*` →
`${NEXT_PUBLIC_API_BASE_URL}/*` for convenience.

## Routes

| Path                | Page                |
| ------------------- | ------------------- |
| `/dashboard`        | Dashboard Home      |
| `/market`           | Market Overview     |
| `/watchlist`        | Watchlist           |
| `/portfolio`        | Portfolio           |
| `/pnl`              | Assets & PnL        |
| `/recommendations`  | Recommendations     |
| `/data-quality`     | Data Quality        |
| `/settings`         | Settings            |

## Scripts

| Command         | Description                          |
| --------------- | ------------------------------------ |
| `pnpm dev`      | Dev server with HMR on :3000         |
| `pnpm build`    | Production build (acts as smoke test)|
| `pnpm start`    | Run the production build             |
| `pnpm lint`     | next lint                            |
| `pnpm typecheck`| tsc --noEmit                         |
| `pnpm format`   | Prettier                             |
