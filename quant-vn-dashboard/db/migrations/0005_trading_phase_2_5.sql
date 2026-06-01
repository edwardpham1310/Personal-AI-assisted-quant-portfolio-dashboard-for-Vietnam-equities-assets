-- 0005_trading_phase_2_5.sql
--
-- Phase 2.5 SSI Trading READ-ONLY + ORDER PREVIEW schema.
--
-- Tables:
--   * trading_accounts          - broker accounts registered for read-only sync
--   * trading_account_snapshots - cash snapshots (future: persisted history)
--   * trading_position_snapshots- position snapshots (future: persisted history)
--   * order_previews            - audit row for every preview generated
--   * trading_audit_logs        - every trading-route action by user_id
--
-- Phase 2.5 does NOT submit orders. The forbidden routes
-- (POST /trading/new-order, /submit-order, /cancel-order) write to
-- trading_audit_logs with action='trading.*_attempt_blocked'.
--
-- Idempotent.

set search_path = public;

-- =============================================================================
-- 1. trading_accounts
-- =============================================================================
create table if not exists public.trading_accounts (
  id                      uuid        primary key default gen_random_uuid(),
  user_id                 uuid        not null references auth.users(id) on delete cascade,
  broker                  text        not null default 'SSI',
  account_number_masked   text        not null,
  account_alias           text,
  read_only_enabled       boolean     not null default true,
  trading_enabled         boolean     not null default false,
  created_at              timestamptz not null default now(),
  updated_at              timestamptz not null default now()
);
create index if not exists trading_accounts_user_id_idx
  on public.trading_accounts(user_id);

alter table public.trading_accounts enable row level security;

drop policy if exists trading_accounts_owner_select on public.trading_accounts;
create policy trading_accounts_owner_select on public.trading_accounts
  for select using (auth.uid() = user_id);

drop policy if exists trading_accounts_owner_insert on public.trading_accounts;
create policy trading_accounts_owner_insert on public.trading_accounts
  for insert with check (auth.uid() = user_id);

drop policy if exists trading_accounts_owner_update on public.trading_accounts;
create policy trading_accounts_owner_update on public.trading_accounts
  for update using (auth.uid() = user_id);

drop policy if exists trading_accounts_owner_delete on public.trading_accounts;
create policy trading_accounts_owner_delete on public.trading_accounts
  for delete using (auth.uid() = user_id);

-- =============================================================================
-- 2. trading_account_snapshots (cash)
-- =============================================================================
create table if not exists public.trading_account_snapshots (
  id                  uuid        primary key default gen_random_uuid(),
  user_id             uuid        not null references auth.users(id) on delete cascade,
  account_id          uuid        not null references public.trading_accounts(id) on delete cascade,
  cash_balance        numeric     not null default 0,
  buying_power        numeric     not null default 0,
  withdrawable_cash   numeric     not null default 0,
  pending_cash        numeric     not null default 0,
  total_stock_value   numeric,
  total_equity        numeric,
  raw_snapshot        jsonb,
  created_at          timestamptz not null default now()
);
create index if not exists trading_account_snapshots_account_idx
  on public.trading_account_snapshots(account_id, created_at desc);

alter table public.trading_account_snapshots enable row level security;
drop policy if exists tas_owner_select on public.trading_account_snapshots;
create policy tas_owner_select on public.trading_account_snapshots
  for select using (auth.uid() = user_id);
drop policy if exists tas_owner_insert on public.trading_account_snapshots;
-- Belt-and-suspenders: ``user_id`` matching auth.uid() AND the referenced
-- ``account_id`` must belong to that same user. Without the EXISTS clause
-- a malicious client could insert a cash snapshot referencing another
-- user's account_id while passing their own user_id.
create policy tas_owner_insert on public.trading_account_snapshots
  for insert with check (
    auth.uid() = user_id
    and exists (
      select 1 from public.trading_accounts a
      where a.id = account_id and a.user_id = auth.uid()
    )
  );

-- =============================================================================
-- 3. trading_position_snapshots
-- =============================================================================
create table if not exists public.trading_position_snapshots (
  id                  uuid        primary key default gen_random_uuid(),
  user_id             uuid        not null references auth.users(id) on delete cascade,
  account_id          uuid        not null references public.trading_accounts(id) on delete cascade,
  symbol              text        not null,
  exchange            text,
  quantity            integer     not null default 0,
  sellable_quantity   integer     not null default 0,
  pending_quantity    integer     not null default 0,
  avg_cost            numeric     not null default 0,
  market_price        numeric,
  market_value        numeric,
  raw_snapshot        jsonb,
  created_at          timestamptz not null default now()
);
create index if not exists trading_position_snapshots_account_sym_idx
  on public.trading_position_snapshots(account_id, symbol);

alter table public.trading_position_snapshots enable row level security;
drop policy if exists tps_owner_select on public.trading_position_snapshots;
create policy tps_owner_select on public.trading_position_snapshots
  for select using (auth.uid() = user_id);
drop policy if exists tps_owner_insert on public.trading_position_snapshots;
-- Same belt-and-suspenders as trading_account_snapshots above.
create policy tps_owner_insert on public.trading_position_snapshots
  for insert with check (
    auth.uid() = user_id
    and exists (
      select 1 from public.trading_accounts a
      where a.id = account_id and a.user_id = auth.uid()
    )
  );

-- =============================================================================
-- 4. order_previews
-- =============================================================================
create table if not exists public.order_previews (
  id                    uuid        primary key default gen_random_uuid(),
  user_id               uuid        not null references auth.users(id) on delete cascade,
  account_id            uuid        not null references public.trading_accounts(id) on delete cascade,
  symbol                text        not null,
  side                  text        not null check (side in ('BUY','SELL')),
  order_type            text        not null check (order_type in ('LIMIT','MARKET','ATO','ATC','MTL')),
  quantity              integer     not null,
  limit_price           numeric     not null,
  estimated_value       numeric     not null,
  estimated_fees        numeric     not null default 0,
  estimated_tax         numeric     not null default 0,
  estimated_vat         numeric     not null default 0,
  estimated_slippage    numeric     not null default 0,
  total_cash_required   numeric,
  net_sell_proceeds     numeric,
  validation_status     text        not null check (validation_status in ('VALID','WARN','REJECTED')),
  warnings              jsonb       not null default '[]'::jsonb,
  rejection_reasons     jsonb       not null default '[]'::jsonb,
  created_at            timestamptz not null default now()
);
create index if not exists order_previews_user_idx
  on public.order_previews(user_id, created_at desc);

alter table public.order_previews enable row level security;
drop policy if exists order_previews_owner_select on public.order_previews;
create policy order_previews_owner_select on public.order_previews
  for select using (auth.uid() = user_id);
drop policy if exists order_previews_owner_insert on public.order_previews;
create policy order_previews_owner_insert on public.order_previews
  for insert with check (auth.uid() = user_id);

-- =============================================================================
-- 5. trading_audit_logs
-- =============================================================================
create table if not exists public.trading_audit_logs (
  id           uuid        primary key default gen_random_uuid(),
  user_id      uuid        not null references auth.users(id) on delete cascade,
  account_id   uuid        references public.trading_accounts(id) on delete set null,
  action       text        not null,
  metadata     jsonb       not null default '{}'::jsonb,
  ip_address   text,
  user_agent   text,
  created_at   timestamptz not null default now()
);
create index if not exists trading_audit_logs_user_idx
  on public.trading_audit_logs(user_id, created_at desc);
create index if not exists trading_audit_logs_action_idx
  on public.trading_audit_logs(action);

alter table public.trading_audit_logs enable row level security;
drop policy if exists trading_audit_owner_select on public.trading_audit_logs;
create policy trading_audit_owner_select on public.trading_audit_logs
  for select using (auth.uid() = user_id);
drop policy if exists trading_audit_owner_insert on public.trading_audit_logs;
create policy trading_audit_owner_insert on public.trading_audit_logs
  for insert with check (auth.uid() = user_id);
