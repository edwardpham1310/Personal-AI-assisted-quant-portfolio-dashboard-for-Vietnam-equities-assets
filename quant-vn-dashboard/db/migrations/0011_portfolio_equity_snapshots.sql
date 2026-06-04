-- 0011_portfolio_equity_snapshots.sql
--
-- Manual-portfolio daily NAV history for the dashboard equity curve.
--
-- The manual portfolio (manual_portfolio_accounts / manual_positions /
-- cash_balances / trade_transactions) only holds *current* state — there is no
-- time series to draw an equity curve from. This table accumulates one
-- point-in-time NAV snapshot per account per trading day (Asia/Ho_Chi_Minh),
-- written by services/portfolio_snapshots.py via POST /portfolio/snapshots/run
-- (dashboard-on-mount or an external cron). Forward-only: the curve starts
-- empty and grows — never back-filled with synthetic NAV.
--
-- RLS owner_select / owner_insert / owner_update only (no delete). UPDATE
-- carries ``with check`` (Phase 2.6/2.7 review lesson). Idempotent.

set search_path = public;

create table if not exists public.portfolio_equity_snapshots (
  id              uuid        primary key default gen_random_uuid(),
  user_id         uuid        not null references auth.users(id) on delete cascade,
  account_id      uuid        not null references public.manual_portfolio_accounts(id) on delete cascade,
  snapshot_date   date        not null,
  ts              timestamptz not null default now(),
  cash            numeric     not null default 0,
  stock_value     numeric     not null default 0,
  total_equity    numeric     not null default 0,
  currency        text        not null default 'VND',
  created_at      timestamptz not null default now(),
  -- One snapshot per account per trading day; the writer upserts on this key.
  unique (account_id, snapshot_date)
);
create index if not exists portfolio_equity_snapshots_acct_idx
  on public.portfolio_equity_snapshots(account_id, snapshot_date);

alter table public.portfolio_equity_snapshots enable row level security;

drop policy if exists pes_owner_select on public.portfolio_equity_snapshots;
create policy pes_owner_select on public.portfolio_equity_snapshots
  for select using (auth.uid() = user_id);

drop policy if exists pes_owner_insert on public.portfolio_equity_snapshots;
create policy pes_owner_insert on public.portfolio_equity_snapshots
  for insert with check (
    auth.uid() = user_id
    and exists (
      select 1 from public.manual_portfolio_accounts a
      where a.id = account_id and a.user_id = auth.uid()
    )
  );

drop policy if exists pes_owner_update on public.portfolio_equity_snapshots;
create policy pes_owner_update on public.portfolio_equity_snapshots
  for update using (auth.uid() = user_id) with check (auth.uid() = user_id);
