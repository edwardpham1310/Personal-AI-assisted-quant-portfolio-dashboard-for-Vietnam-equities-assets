# Signal Scanner — Data Flow & Caching

Companion to [`scanner-signals.md`](./scanner-signals.md). Describes how
scanner endpoints fetch market data, where results are cached, and the
budget of upstream (SSI) calls per request.

## Trust boundary

The FastAPI service in `apps/api` is the only process allowed to talk to
SSI FastConnect. The browser never reaches SSI directly — see
`apps/web/src/no-direct-ssi.test.ts`.

## Data flow diagram

```
Browser (Next.js /watchlist)
   │
   │ HTTPS + Supabase JWT
   ▼
FastAPI  /scanner/watchlist/{id}
   │
   ├─ SupabaseDB.select("watchlists" / "watchlist_items")  (RLS by JWT)
   │
   ├─ for each symbol (asyncio.gather, cap=5 via semaphore):
   │     1. cache.get_json("scanner:symbol:{SYM}")  ── HIT → return cached
   │     2. provider.get_daily_ohlcv(SYM, today-80d, today)
   │     3. provider.get_latest_quotes([SYM])
   │     4. scanner_service.scan_symbol(SYM, bars, latest_quote)
   │     5. cache.set_json("scanner:symbol:{SYM}", result, ttl=60)
   │
   ▼
MarketDataProvider (SSI FastConnect / MockProvider)
```

Browser separately subscribes to `GET /stream/watchlist/{id}` for live
quotes (SSE). The scanner table merges those quotes onto each row to
overlay `last_price` + `stale` without re-issuing scanner scans.

## Cache layers

| Key                            | TTL  | Contents                  | Producer                  | Consumer                |
| ------------------------------ | ---- | ------------------------- | ------------------------- | ----------------------- |
| `scanner:symbol:{SYM}`         | 60 s | Full `ScannerResult` JSON | `_scan_one()` after fetch | `_scan_one()` (this and other users) |
| `quote:{SYM}` (existing)       | varies (provider TTL) | Latest `Quote` snapshot | `MarketPoller` background loop | `/market/live/quotes`, SSE stream |
| `index:{CODE}` (existing)      | varies | Index snapshot           | `MarketPoller`            | `/market/live/indices`, market overview SSE |
| `last_poll` (existing)         | n/a  | Poller heartbeat          | `MarketPoller`            | `/market/live/status` |

Scanner cache keys are **symbol-scoped, not user-scoped**. Output depends
only on public market data, so a hit warmed by user A is correctly
reused by user B. No PII is stored under these keys.

## SSI call budget per request

| Route                                         | Cold cache (worst case) | Warm cache | Notes |
| --------------------------------------------- | ----------------------- | ---------- | ----- |
| `GET /scanner/symbol/{SYM}`                   | 1× daily OHLCV + 1× quote | 0 | 80-day daily fetch + 1-symbol quote |
| `GET /scanner/watchlist/{id}` (N=30 symbols)  | 30× daily + 30× quote (= 60 calls) over ~6 batches of 5 concurrent | 0 | Semaphore caps concurrent SSI calls at 5 |
| `GET /scanner/universe?vn30=true`             | 1× index components + 30× daily + 30× quote (= 61 calls) | 0 (after first warm-up) | Same semaphore |

A fully warm cache (every symbol scanned in the last 60s by anyone)
turns every batch endpoint into pure Redis reads.

## Stale-data behaviour

- Backend marks `Quote.stale = true` when `now - quote.ts >
  ssi_quote_stale_seconds` (configurable in `core.config.Settings`).
- The frontend renders a `Stale` badge if either the live quote is
  stale OR `ScannerResult.as_of` is older than 5 minutes
  (`SCANNER_STALE_MS` in `useScanner.ts`).
- The scanner does **not** currently short-circuit on market-closed /
  weekend timestamps. A cold cache on Saturday will still issue 30×
  daily fetches against SSI for a VN30 scan; SSI returns the same
  Friday bars but a quota call is consumed.

## Failure isolation

`_scan_one()` returns `None` when the provider rejects a symbol
(unknown ticker, rate limit, network error). Batch endpoints
(`/scanner/watchlist`, `/scanner/universe`) drop those silently and
return the symbols that succeeded. The single-symbol endpoint surfaces
unknown tickers as `404`.

This is deliberate: one bad ticker on a 30-symbol watchlist should not
fail the whole table. The trade-off is that the UI cannot today
distinguish "symbol failed" from "symbol filtered". A follow-up
improvement is per-symbol error annotation in the response.

## Recommendations

**P1 — Cache daily OHLCV separately from scanner result.**
Today every cache miss refetches ~80 days of daily bars from SSI even
though daily bars only change at session close. Add a second cache
layer:
- Key: `ohlcv:daily:{SYM}:{YYYY-MM-DD}` (or `ohlcv:daily:{SYM}` with
  longer TTL, e.g. 4 h during market hours, 12 h overnight).
- Use it inside `_scan_one()` so a miss on `scanner:symbol:{SYM}` still
  hits the OHLCV layer and only recomputes the indicators.

Effort: small. Win: cuts cold-cache SSI fan-out roughly in half on
batch routes.

**P2 — Pre-warm VN30 via the existing `MarketPoller`.**
The poller already cycles core symbols. Add a "scanner pre-warm" task
that, once per minute, walks VN30 and primes `scanner:symbol:{SYM}` so
the universe endpoint is essentially always warm. Effort: medium.

**P3 — Surface per-symbol errors instead of dropping silently.**
Change the batch response to `{ "results": [...], "skipped": [{symbol,
reason}, ...] }` (additive — keep the array form behind a query flag
for backward compatibility). Effort: small. UX win: small but
non-zero.

**P3 — Short-circuit on closed-market days.**
Use `services.market_cache.get_last_poll()` to detect a clearly stale
session and serve the most recent warm cache without issuing fresh SSI
calls. Effort: small.

**P3 — Surface `warnings` from `ScannerResult` in the UI table.**
The backend already emits warnings like `insufficient_history` and
implicitly `bar.value missing → using close*volume`. The frontend
should render an icon when warnings are present so a low liquidity
score on a symbol with `bar.value` missing isn't quietly trusted.
Effort: small.

## Open questions for future iterations

- Should scanner results be stored in Postgres (history table) so the
  user can see how status flipped over the last 5 days? Phase 1 keeps
  it ephemeral in Redis only.
- Should the per-symbol scan be cached longer on weekends / holidays?
- Should the universe endpoint accept other indices (VN100, VNALL,
  custom sector baskets) — and what's the SSI call ceiling for a
  300-symbol scan?

## Related docs

- [`scanner-signals.md`](./scanner-signals.md) — math & signal taxonomy
- [`architecture.md`](./architecture.md) — overall MVP architecture
- [`assumptions.md`](./assumptions.md) — trust model
