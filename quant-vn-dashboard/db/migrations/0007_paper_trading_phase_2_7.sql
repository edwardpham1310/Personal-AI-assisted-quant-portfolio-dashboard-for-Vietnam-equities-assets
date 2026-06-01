-- 0007_paper_trading_phase_2_7.sql
--
-- Phase 2.7 Paper trading engine — simulated only, no real broker.
--
-- 7 tables: paper_accounts, paper_orders, paper_fills, paper_positions,
-- paper_cash_ledger, paper_equity_curve, paper_audit_logs.
--
-- RLS owner_select/insert/update/delete on every table. UPDATE policies
-- include ``with check`` (lesson from Phase 2.6 review).
--
-- Idempotent.

set search_path = public;

-- =============================================================================
-- paper_accounts
-- =============================================================================
create table if not exists public.paper_accounts (
  id              uuid        primary key default gen_random_uuid(),
  user_id         uuid        not null references auth.users(id) on delete cascade,
  name            text        not null,
  starting_cash   numeric     not null default 100000000 check (starting_cash >= 0),
  current_cash    numeric     not null default 100000000 check (current_cash >= 0),
  currency        text        not null default 'VND',
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now()
);
create index if not exists paper_accounts_user_idx on public.paper_accounts(user_id);

alter table public.paper_accounts enable row level security;
drop policy if exists pacc_owner_select on public.paper_accounts;
create policy pacc_owner_select on public.paper_accounts
  for select using (auth.uid() = user_id);
drop policy if exists pacc_owner_insert on public.paper_accounts;
create policy pacc_owner_insert on public.paper_accounts
  for insert with check (auth.uid() = user_id);
drop policy if exists pacc_owner_update on public.paper_accounts;
create policy pacc_owner_update on public.paper_accounts
  for update using (auth.uid() = user_id) with check (auth.uid() = user_id);
drop policy if exists pacc_owner_delete on public.paper_accounts;
create policy pacc_owner_delete on public.paper_accounts
  for delete using (auth.uid() = user_id);

-- =============================================================================
-- paper_orders
-- =============================================================================
create table if not exists public.paper_orders (
  id                  uuid        primary key default gen_random_uuid(),
  user_id             uuid        not null references auth.users(id) on delete cascade,
  paper_account_id    uuid        not null references public.paper_accounts(id) on delete cascade,
  source_type         text        not null default 'MANUAL'
                                  check (source_type in ('MANUAL','RECOMMENDATION','STRATEGY')),
  source_id           text,
  symbol              text        not null,
  side                text        not null check (side in ('BUY','SELL')),
  order_type          text        not null check (order_type in ('MARKET','LIMIT')),
  quantity            integer     not null check (quantity > 0),
  limit_price         numeric,
  status              text        not null default 'DRAFT'
                                  check (status in ('DRAFT','SUBMITTED','FILLED','PARTIALLY_FILLED','REJECTED','CANCELLED')),
  rejection_reason    text,
  created_at          timestamptz not null default now(),
  updated_at          timestamptz not null default now()
);
create index if not exists paper_orders_acct_idx on public.paper_orders(paper_account_id, created_at desc);

alter table public.paper_orders enable row level security;
drop policy if exists pord_owner_select on public.paper_orders;
create policy pord_owner_select on public.paper_orders
  for select using (auth.uid() = user_id);
drop policy if exists pord_owner_insert on public.paper_orders;
create policy pord_owner_insert on public.paper_orders
  for insert with check (
    auth.uid() = user_id
    and exists (select 1 from public.paper_accounts a where a.id = paper_account_id and a.user_id = auth.uid())
  );
drop policy if exists pord_owner_update on public.paper_orders;
create policy pord_owner_update on public.paper_orders
  for update using (auth.uid() = user_id) with check (auth.uid() = user_id);

-- Phase 2.7 review fix (CRITICAL): an UPDATE policy that only checks
-- ownership lets a JWT-wielding client flip ``status`` between any
-- valid enum value via PostgREST — including REJECTED→FILLED (no
-- corresponding fill row, no cost debit). Lock down legal transitions
-- with a BEFORE UPDATE trigger.
--
-- Allowed transitions (the orchestrator's actual flow):
--   DRAFT      → SUBMITTED | REJECTED | CANCELLED
--   SUBMITTED  → FILLED | PARTIALLY_FILLED | CANCELLED | REJECTED
--   PARTIALLY_FILLED → FILLED | CANCELLED
--   FILLED     → FILLED               (terminal — same-state writes ok)
--   CANCELLED  → CANCELLED            (terminal)
--   REJECTED   → REJECTED             (terminal)
create or replace function public.check_paper_order_transition()
returns trigger as $$
begin
  if old.status = new.status then
    return new;
  end if;
  -- Terminal states cannot be left.
  if old.status in ('FILLED','CANCELLED','REJECTED') then
    raise exception 'paper_orders.status: cannot leave terminal state %', old.status;
  end if;
  -- Allowed forward transitions from non-terminal states.
  if old.status = 'DRAFT' and new.status in ('SUBMITTED','REJECTED','CANCELLED') then
    return new;
  end if;
  if old.status = 'SUBMITTED'
     and new.status in ('FILLED','PARTIALLY_FILLED','CANCELLED','REJECTED') then
    return new;
  end if;
  if old.status = 'PARTIALLY_FILLED' and new.status in ('FILLED','CANCELLED') then
    return new;
  end if;
  raise exception 'paper_orders.status: illegal transition % → %', old.status, new.status;
end;
$$ language plpgsql;

drop trigger if exists paper_orders_state_machine on public.paper_orders;
create trigger paper_orders_state_machine
  before update on public.paper_orders
  for each row execute function public.check_paper_order_transition();

-- =============================================================================
-- paper_fills
-- =============================================================================
create table if not exists public.paper_fills (
  id                  uuid        primary key default gen_random_uuid(),
  user_id             uuid        not null references auth.users(id) on delete cascade,
  paper_account_id    uuid        not null references public.paper_accounts(id) on delete cascade,
  paper_order_id      uuid        not null references public.paper_orders(id) on delete cascade,
  symbol              text        not null,
  side                text        not null check (side in ('BUY','SELL')),
  quantity            integer     not null check (quantity > 0),
  fill_price          numeric     not null check (fill_price > 0),
  gross_value         numeric     not null,
  brokerage_fee       numeric     not null default 0,
  vat                 numeric     not null default 0,
  sell_tax            numeric     not null default 0,
  slippage            numeric     not null default 0,
  net_cash_impact     numeric     not null,
  filled_at           timestamptz not null default now()
);
create index if not exists paper_fills_acct_idx on public.paper_fills(paper_account_id, filled_at desc);
create index if not exists paper_fills_unsettled_idx on public.paper_fills(paper_account_id, filled_at) where side in ('BUY','SELL');

alter table public.paper_fills enable row level security;
drop policy if exists pfill_owner_select on public.paper_fills;
create policy pfill_owner_select on public.paper_fills
  for select using (auth.uid() = user_id);
drop policy if exists pfill_owner_insert on public.paper_fills;
-- Phase 2.7 review fix (CRITICAL): the original policy let a
-- JWT-wielding client INSERT arbitrary fill rows with any
-- ``paper_order_id`` + fabricated ``fill_price``/``quantity``/
-- ``net_cash_impact``, even though no live route exposes this. Tighten
-- the policy to require the referenced order belongs to the same
-- ``paper_account_id`` AND ``user_id``.
create policy pfill_owner_insert on public.paper_fills
  for insert with check (
    auth.uid() = user_id
    and exists (
      select 1 from public.paper_orders o
      where o.id = paper_order_id
        and o.paper_account_id = paper_fills.paper_account_id
        and o.user_id = auth.uid()
    )
  );

-- =============================================================================
-- paper_positions
-- =============================================================================
create table if not exists public.paper_positions (
  id                  uuid        primary key default gen_random_uuid(),
  user_id             uuid        not null references auth.users(id) on delete cascade,
  paper_account_id    uuid        not null references public.paper_accounts(id) on delete cascade,
  symbol              text        not null,
  quantity            integer     not null default 0 check (quantity >= 0),
  sellable_quantity   integer     not null default 0 check (sellable_quantity >= 0),
  pending_quantity    integer     not null default 0 check (pending_quantity >= 0),
  avg_cost            numeric     not null default 0 check (avg_cost >= 0),
  market_price        numeric,
  market_value        numeric,
  unrealized_pnl      numeric,
  updated_at          timestamptz not null default now(),
  unique (paper_account_id, symbol)
);
create index if not exists paper_positions_acct_idx on public.paper_positions(paper_account_id);

alter table public.paper_positions enable row level security;
drop policy if exists ppos_owner_select on public.paper_positions;
create policy ppos_owner_select on public.paper_positions
  for select using (auth.uid() = user_id);
drop policy if exists ppos_owner_insert on public.paper_positions;
create policy ppos_owner_insert on public.paper_positions
  for insert with check (
    auth.uid() = user_id
    and exists (select 1 from public.paper_accounts a where a.id = paper_account_id and a.user_id = auth.uid())
  );
drop policy if exists ppos_owner_update on public.paper_positions;
create policy ppos_owner_update on public.paper_positions
  for update using (auth.uid() = user_id) with check (auth.uid() = user_id);

-- =============================================================================
-- paper_cash_ledger
-- =============================================================================
create table if not exists public.paper_cash_ledger (
  id                  uuid        primary key default gen_random_uuid(),
  user_id             uuid        not null references auth.users(id) on delete cascade,
  paper_account_id    uuid        not null references public.paper_accounts(id) on delete cascade,
  event_type          text        not null check (event_type in
                        ('DEPOSIT','BUY_DEBIT','SELL_PROCEEDS_PENDING','SELL_PROCEEDS_SETTLED','FEE')),
  amount              numeric     not null,
  settled_date        date        not null,
  status              text        not null default 'SETTLED' check (status in ('SETTLED','PENDING')),
  metadata            jsonb       not null default '{}'::jsonb,
  created_at          timestamptz not null default now()
);
create index if not exists paper_cash_ledger_acct_idx on public.paper_cash_ledger(paper_account_id, created_at desc);
create index if not exists paper_cash_ledger_status_idx on public.paper_cash_ledger(paper_account_id, status);

alter table public.paper_cash_ledger enable row level security;
drop policy if exists pled_owner_select on public.paper_cash_ledger;
create policy pled_owner_select on public.paper_cash_ledger
  for select using (auth.uid() = user_id);
drop policy if exists pled_owner_insert on public.paper_cash_ledger;
create policy pled_owner_insert on public.paper_cash_ledger
  for insert with check (
    auth.uid() = user_id
    and exists (select 1 from public.paper_accounts a where a.id = paper_account_id and a.user_id = auth.uid())
  );
drop policy if exists pled_owner_update on public.paper_cash_ledger;
create policy pled_owner_update on public.paper_cash_ledger
  for update using (auth.uid() = user_id) with check (auth.uid() = user_id);

-- =============================================================================
-- paper_equity_curve
-- =============================================================================
create table if not exists public.paper_equity_curve (
  id                  uuid        primary key default gen_random_uuid(),
  user_id             uuid        not null references auth.users(id) on delete cascade,
  paper_account_id    uuid        not null references public.paper_accounts(id) on delete cascade,
  timestamp           timestamptz not null,
  cash                numeric     not null default 0,
  pending_cash        numeric     not null default 0,
  stock_value         numeric     not null default 0,
  total_equity        numeric     not null default 0,
  drawdown            numeric     not null default 0,
  created_at          timestamptz not null default now()
);
create index if not exists paper_equity_curve_acct_idx on public.paper_equity_curve(paper_account_id, timestamp);

alter table public.paper_equity_curve enable row level security;
drop policy if exists peq_owner_select on public.paper_equity_curve;
create policy peq_owner_select on public.paper_equity_curve
  for select using (auth.uid() = user_id);
drop policy if exists peq_owner_insert on public.paper_equity_curve;
create policy peq_owner_insert on public.paper_equity_curve
  for insert with check (
    auth.uid() = user_id
    and exists (select 1 from public.paper_accounts a where a.id = paper_account_id and a.user_id = auth.uid())
  );

-- =============================================================================
-- paper_audit_logs
-- =============================================================================
create table if not exists public.paper_audit_logs (
  id                  uuid        primary key default gen_random_uuid(),
  user_id             uuid        not null references auth.users(id) on delete cascade,
  paper_account_id    uuid        references public.paper_accounts(id) on delete set null,
  action              text        not null,
  metadata            jsonb       not null default '{}'::jsonb,
  created_at          timestamptz not null default now()
);
create index if not exists paper_audit_logs_user_idx on public.paper_audit_logs(user_id, created_at desc);

alter table public.paper_audit_logs enable row level security;
drop policy if exists pal_owner_select on public.paper_audit_logs;
create policy pal_owner_select on public.paper_audit_logs
  for select using (auth.uid() = user_id);
drop policy if exists pal_owner_insert on public.paper_audit_logs;
create policy pal_owner_insert on public.paper_audit_logs
  for insert with check (auth.uid() = user_id);
