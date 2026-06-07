# Equity curve & NAV history

The dashboard equity curve is **real, forward-only NAV history** for the user's
default manual-portfolio account. It is never back-filled or synthesised — it
only contains days that were actually snapshotted.

## Data model — migration `0011_portfolio_equity_snapshots.sql`

Table `public.portfolio_equity_snapshots` (one row per account per trading day):

| column | meaning |
|---|---|
| `id` | uuid PK |
| `user_id` | owner (FK `auth.users`) |
| `account_id` | FK `manual_portfolio_accounts` |
| `snapshot_date` | trading day (ICT), `unique(account_id, snapshot_date)` |
| `ts` | exact capture time |
| `cash`, `stock_value`, `total_equity` | NAV components (VND) |

**RLS:** `owner_select` / `owner_insert` / `owner_update` only — a user can read
and write **only** their own rows (`auth.uid() = user_id`), with the insert
policy also checking account ownership. No delete policy (forward-only append).

### Apply the migration

Migrations are plain SQL applied in order. Via the Supabase SQL editor or psql:

```bash
psql "$DATABASE_URL" -f db/migrations/0011_portfolio_equity_snapshots.sql
```

It is **idempotent** (`create table if not exists`, `drop policy if exists` +
`create policy`), so re-applying is safe.

### Check it applied

```sql
-- table exists
select to_regclass('public.portfolio_equity_snapshots');
-- RLS on + policies present
select relrowsecurity from pg_class where relname = 'portfolio_equity_snapshots';
select polname from pg_policy
  where polrelid = 'public.portfolio_equity_snapshots'::regclass;
```

## How snapshots are produced

NAV is computed by `services/portfolio_snapshots.compute_nav` from **real**
sources — `cash_balances` + `manual_positions` marked with the live quote cache
— using the *same* definition as `/assets/summary.total_equity`
(`settled + pending + stock_value + advanced − advance_liability`). Two writers:

1. **Dashboard on mount** — the equity-curve hook fires
   `POST /portfolio/snapshots/run` (idempotent per day).
2. **Cron (reliable producer)** — `scripts/snapshot-equity.sh`, run Mon–Fri
   after the HOSE close, calls the same endpoint with a dashboard **user**
   token (RLS-scoped). See the script header for the crontab line.

Both paths are **read-only valuation persistence** — no orders, no trading.

### Cold-cache safety (reliable real data)

If a held position has **no quote** (poller off / cache cold), its market value
would be 0 and the NAV would understate. The writer **refuses to persist** such
a point and returns:

```json
{ "recorded": false, "reason": "quotes_unavailable", "warnings": ["quote_missing:FPT"] }
```

So the curve only ever stores **fully-marked** NAV. Keep the market poller warm
(`ENABLE_MARKET_POLLER=true`) around snapshot time, or the cron re-runs next day.
Cash-only accounts (no positions) always record.

## Expected behavior — before / after the first snapshot

- **Before any snapshot** (new account, or only cold-cache runs so far):
  `GET /portfolio/equity-curve` returns `[]`; the chart shows the honest empty
  state *"No portfolio history yet…"*. This is correct — no NAV is invented.
- **After the first successful snapshot:** the curve returns ascending-by-date
  `EquityPoint`s (`ts`, `equity`) and grows one point per snapshotted trading
  day. `start`/`end` query params filter a calendar window (inclusive);
  inverted ranges → `400`.

## Browser smoke checklist

1. Open the Dashboard (or Portfolio) → the chart seeds today's point (if the
   quote cache is warm). With a cold cache it stays empty (honest), no error.
2. Over several trading days, the line renders **oldest left → newest right**.
3. The range dropdown filters the window; empty windows show the empty state.
4. No console errors.

## Trading safety

The equity-curve/snapshot path performs **no** order placement or execution. The
snapshot endpoint and cron write only the caller's own account (RLS-scoped) and
read live quotes for valuation only. `submit_order` remains 501; order-placement
flags remain false.
