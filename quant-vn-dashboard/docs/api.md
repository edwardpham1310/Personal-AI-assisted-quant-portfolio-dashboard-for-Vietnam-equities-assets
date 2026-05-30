# API Surface

OpenAPI docs are served at `/docs` (Swagger UI) and `/redoc` when the API is
running locally.

## Conventions

- All routes return JSON unless noted (SSE returns `text/event-stream`).
- All non-health routes require `Authorization: Bearer <supabase_jwt>`.
- Successful responses use HTTP 200/201. Errors use 4xx with a body of
  `{ "detail": "<message>" }`.

## Endpoints (MVP scaffold)

### Health

| Method | Path       | Description                                |
| ------ | ---------- | ------------------------------------------ |
| GET    | `/health`  | Liveness probe. Returns env + version.     |

### Auth (`/auth`)

| Method | Path           | Description                                  |
| ------ | -------------- | -------------------------------------------- |
| GET    | `/auth/me`     | Echo the authenticated user (placeholder).   |

### Market (`/market`)

| Method | Path                          | Description                              |
| ------ | ----------------------------- | ---------------------------------------- |
| GET    | `/market/quote/{symbol}`      | Latest quote from Redis hot cache.       |
| GET    | `/market/indices`             | Snapshot of major VN indices.            |
| GET    | `/market/bars/{symbol}`       | Intraday or daily OHLCV (params).        |

### Stream (`/stream`)

| Method | Path                | Description                                  |
| ------ | ------------------- | -------------------------------------------- |
| GET    | `/stream/quotes`    | SSE stream of quote updates for symbols.     |
| GET    | `/stream/portfolio` | SSE stream of portfolio PnL recalculations.  |

### Portfolio (`/portfolio`)

| Method | Path                      | Description                              |
| ------ | ------------------------- | ---------------------------------------- |
| GET    | `/portfolio`              | Current user's portfolios.               |
| POST   | `/portfolio`              | Create a portfolio.                      |
| GET    | `/portfolio/{id}`         | Portfolio detail (holdings, PnL).        |
| POST   | `/portfolio/{id}/txn`     | Record a manual transaction.             |

### Recommendations (`/recommendations`)

| Method | Path                            | Description                            |
| ------ | ------------------------------- | -------------------------------------- |
| GET    | `/recommendations`              | Latest recommendations for the user.   |
| POST   | `/recommendations/{id}/ack`     | Acknowledge / dismiss a suggestion.    |

### System (`/system`)

| Method | Path                    | Description                                  |
| ------ | ----------------------- | -------------------------------------------- |
| GET    | `/system/status`        | Ingest freshness, SSI status, error counts.  |
| GET    | `/system/data-quality`  | Recent data quality issues.                  |

> ⚠️ Phase 1 is recommend-only. There is **no** order placement endpoint.
