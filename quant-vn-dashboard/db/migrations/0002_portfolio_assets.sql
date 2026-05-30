-- 0002_portfolio_assets.sql
--
-- Portfolio valuation + assets/PnL MVP.
--   * Adds sellable/pending/last_marked_at columns to manual_positions
--   * Adds cash_balances (1 row per account) and trade_transactions
--   * Updated-at triggers, indexes, and RLS policies that mirror 0001_init.sql
--
-- Idempotent: safe to re-run on a project already at 0001.

set search_path = public;

-- =============================================================================
-- 1. manual_positions — extend with T+2 settlement bookkeeping
-- =============================================================================
alter table public.manual_positions
  add column if not exists sellable_quantity integer not null default 0;
alter table public.manual_positions
  add column if not exists pending_quantity integer not null default 0;
alter table public.manual_positions
  add column if not exists last_marked_at timestamptz;

-- =============================================================================
-- 2. cash_balances — one row per account
-- =============================================================================
create table if not exists public.cash_balances (
  id                      uuid           primary key default gen_random_uuid(),
  account_id              uuid           not null references public.manual_portfolio_accounts(id) on delete cascade,
  settled_cash            numeric(20, 4) not null default 0 check (settled_cash >= 0),
  pending_cash            numeric(20, 4) not null default 0 check (pending_cash >= 0),
  advanced_cash           numeric(20, 4) not null default 0 check (advanced_cash >= 0),
  cash_advance_liability  numeric(20, 4) not null default 0 check (cash_advance_liability >= 0),
  withdrawable_cash       numeric(20, 4) not null default 0 check (withdrawable_cash >= 0),
  currency                text           not null default 'VND',
  as_of                   timestamptz    not null default now(),
  created_at              timestamptz    not null default now(),
  updated_at              timestamptz    not null default now(),
  unique (account_id)
);
create index if not exists idx_cash_balances_account on public.cash_balances(account_id);

-- =============================================================================
-- 3. trade_transactions — append-only ledger
-- =============================================================================
create table if not exists public.trade_transactions (
  id                  uuid           primary key default gen_random_uuid(),
  account_id          uuid           not null references public.manual_portfolio_accounts(id) on delete cascade,
  symbol              text           not null,
  exchange            text           not null default 'HOSE' check (exchange in ('HOSE', 'HNX', 'UPCOM')),
  side                text           not null check (side in ('BUY', 'SELL')),
  quantity            integer        not null check (quantity > 0),
  price               numeric(20, 4) not null check (price >= 0),
  trade_date          date           not null,
  settlement_date     date,
  brokerage_fee       numeric(20, 4) not null default 0,
  vat                 numeric(20, 4) not null default 0,
  sell_tax            numeric(20, 4) not null default 0,
  cash_advance_fee    numeric(20, 4) not null default 0,
  slippage_estimate   numeric(20, 4) not null default 0,
  note                text,
  created_at          timestamptz    not null default now()
);
create index if not exists idx_trade_transactions_account_date
  on public.trade_transactions(account_id, trade_date desc);

-- =============================================================================
-- Trigger: keep cash_balances.updated_at fresh
-- =============================================================================
drop trigger if exists cash_balances_set_updated_at on public.cash_balances;
create trigger cash_balances_set_updated_at before update on public.cash_balances
  for each row execute function public.set_updated_at();

-- =============================================================================
-- RLS — enable + owner policies that defer to manual_portfolio_accounts
-- =============================================================================
alter table public.cash_balances       enable row level security;
alter table public.trade_transactions  enable row level security;

drop policy if exists cash_balances_owner on public.cash_balances;
create policy cash_balances_owner on public.cash_balances
  for all using (
    exists (select 1 from public.manual_portfolio_accounts a
            where a.id = cash_balances.account_id and a.user_id = auth.uid())
  )
  with check (
    exists (select 1 from public.manual_portfolio_accounts a
            where a.id = cash_balances.account_id and a.user_id = auth.uid())
  );

drop policy if exists trade_transactions_owner on public.trade_transactions;
create policy trade_transactions_owner on public.trade_transactions
  for all using (
    exists (select 1 from public.manual_portfolio_accounts a
            where a.id = trade_transactions.account_id and a.user_id = auth.uid())
  )
  with check (
    exists (select 1 from public.manual_portfolio_accounts a
            where a.id = trade_transactions.account_id and a.user_id = auth.uid())
  );
