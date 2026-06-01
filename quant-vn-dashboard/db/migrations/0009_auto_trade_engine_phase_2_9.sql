-- 0009_auto_trade_engine_phase_2_9.sql
--
-- Phase 2.9 Guarded auto trading engine.
--
-- Tables:
--   * auto_trade_runs           — one row per start/stop cycle
--   * auto_trade_decisions      — one row per evaluated candidate
--   * auto_trade_orders         — linkage to paper_orders / live_order_intents
--   * auto_trade_risk_counters  — per (user, account, trading_date) running totals
--
-- ``trading_audit_logs`` (from 0005) is reused for AUTO_TRADE_* engine actions.
--
-- All UPDATE policies use ``with check``. State-transition trigger
-- guards run.status against laundering — same pattern as paper_orders
-- (0007 review fix) and live_order_intents (0008).
--
-- Idempotent.

set search_path = public;

-- =============================================================================
-- 1. auto_trade_runs
-- =============================================================================
create table if not exists public.auto_trade_runs (
  id              uuid        primary key default gen_random_uuid(),
  user_id         uuid        not null references auth.users(id) on delete cascade,
  account_id      uuid        not null references public.trading_accounts(id) on delete cascade,
  mode            text        not null check (mode in ('OFF','PAPER_ONLY','LIVE_MANUAL_CONFIRM','LIVE_AUTO')),
  strategy_id     text        not null default 'default',
  status          text        not null default 'STARTED'
                              check (status in (
                                'STARTED','RUNNING','PAUSED','STOPPED','EMERGENCY_STOPPED','FAILED'
                              )),
  started_at      timestamptz,
  stopped_at      timestamptz,
  metadata        jsonb       not null default '{}'::jsonb,
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now()
);
create index if not exists auto_trade_runs_user_idx on public.auto_trade_runs(user_id, created_at desc);
create index if not exists auto_trade_runs_acct_status_idx on public.auto_trade_runs(account_id, status);

alter table public.auto_trade_runs enable row level security;
drop policy if exists atr_owner_select on public.auto_trade_runs;
create policy atr_owner_select on public.auto_trade_runs
  for select using (auth.uid() = user_id);
drop policy if exists atr_owner_insert on public.auto_trade_runs;
create policy atr_owner_insert on public.auto_trade_runs
  for insert with check (
    auth.uid() = user_id
    and exists (select 1 from public.trading_accounts a where a.id = account_id and a.user_id = auth.uid())
  );
drop policy if exists atr_owner_update on public.auto_trade_runs;
create policy atr_owner_update on public.auto_trade_runs
  for update using (auth.uid() = user_id) with check (auth.uid() = user_id);

create or replace function public.check_auto_trade_run_transition()
returns trigger as $$
begin
  if old.status = new.status then
    return new;
  end if;
  if old.status in ('STOPPED','EMERGENCY_STOPPED','FAILED') then
    raise exception 'auto_trade_runs.status: cannot leave terminal state %', old.status;
  end if;
  if old.status = 'STARTED'
     and new.status in ('RUNNING','STOPPED','FAILED','EMERGENCY_STOPPED') then
    return new;
  end if;
  if old.status = 'RUNNING'
     and new.status in ('PAUSED','STOPPED','EMERGENCY_STOPPED','FAILED') then
    return new;
  end if;
  if old.status = 'PAUSED'
     and new.status in ('RUNNING','STOPPED','EMERGENCY_STOPPED','FAILED') then
    return new;
  end if;
  raise exception 'auto_trade_runs.status: illegal transition % → %',
    old.status, new.status;
end;
$$ language plpgsql;

drop trigger if exists auto_trade_runs_state_machine on public.auto_trade_runs;
create trigger auto_trade_runs_state_machine
  before update on public.auto_trade_runs
  for each row execute function public.check_auto_trade_run_transition();

-- =============================================================================
-- 2. auto_trade_decisions
-- =============================================================================
create table if not exists public.auto_trade_decisions (
  id                  uuid        primary key default gen_random_uuid(),
  user_id             uuid        not null references auth.users(id) on delete cascade,
  account_id          uuid        not null references public.trading_accounts(id) on delete cascade,
  run_id              uuid        not null references public.auto_trade_runs(id) on delete cascade,
  symbol              text        not null,
  recommendation_id   text,
  action              text        not null,
  decision            text        not null,
  reason              jsonb       not null default '{}'::jsonb,
  risk_snapshot       jsonb       not null default '{}'::jsonb,
  created_at          timestamptz not null default now()
);
create index if not exists auto_trade_decisions_run_idx on public.auto_trade_decisions(run_id, created_at desc);

alter table public.auto_trade_decisions enable row level security;
drop policy if exists atd_owner_select on public.auto_trade_decisions;
create policy atd_owner_select on public.auto_trade_decisions
  for select using (auth.uid() = user_id);
drop policy if exists atd_owner_insert on public.auto_trade_decisions;
create policy atd_owner_insert on public.auto_trade_decisions
  for insert with check (
    auth.uid() = user_id
    and exists (select 1 from public.auto_trade_runs r where r.id = run_id and r.user_id = auth.uid())
  );

-- =============================================================================
-- 3. auto_trade_orders (linkage to paper_orders / live_order_intents)
-- =============================================================================
create table if not exists public.auto_trade_orders (
  id                       uuid        primary key default gen_random_uuid(),
  user_id                  uuid        not null references auth.users(id) on delete cascade,
  account_id               uuid        not null references public.trading_accounts(id) on delete cascade,
  run_id                   uuid        not null references public.auto_trade_runs(id) on delete cascade,
  decision_id              uuid        not null references public.auto_trade_decisions(id) on delete cascade,
  live_order_intent_id     uuid        references public.live_order_intents(id) on delete set null,
  paper_order_id           uuid        references public.paper_orders(id) on delete set null,
  mode                     text        not null check (mode in ('PAPER','MANUAL_CONFIRM','LIVE_DRY_RUN','LIVE')),
  status                   text        not null,
  created_at               timestamptz not null default now()
);
create index if not exists auto_trade_orders_run_idx on public.auto_trade_orders(run_id, created_at desc);
create index if not exists auto_trade_orders_cooldown_idx on public.auto_trade_orders(account_id, created_at desc);

alter table public.auto_trade_orders enable row level security;
drop policy if exists ato_owner_select on public.auto_trade_orders;
create policy ato_owner_select on public.auto_trade_orders
  for select using (auth.uid() = user_id);
drop policy if exists ato_owner_insert on public.auto_trade_orders;
create policy ato_owner_insert on public.auto_trade_orders
  for insert with check (
    auth.uid() = user_id
    and exists (select 1 from public.auto_trade_runs r where r.id = run_id and r.user_id = auth.uid())
  );

-- =============================================================================
-- 4. auto_trade_risk_counters
-- =============================================================================
create table if not exists public.auto_trade_risk_counters (
  id                       uuid        primary key default gen_random_uuid(),
  user_id                  uuid        not null references auth.users(id) on delete cascade,
  account_id               uuid        not null references public.trading_accounts(id) on delete cascade,
  trading_date             date        not null,
  orders_count             integer     not null default 0,
  gross_order_value        numeric     not null default 0,
  realized_loss            numeric     not null default 0,
  unrealized_loss          numeric     not null default 0,
  daily_loss               numeric     not null default 0,
  updated_at               timestamptz not null default now(),
  unique (user_id, account_id, trading_date)
);
create index if not exists auto_trade_risk_counters_user_idx
  on public.auto_trade_risk_counters(user_id, trading_date desc);

alter table public.auto_trade_risk_counters enable row level security;
drop policy if exists atrc_owner_select on public.auto_trade_risk_counters;
create policy atrc_owner_select on public.auto_trade_risk_counters
  for select using (auth.uid() = user_id);
drop policy if exists atrc_owner_insert on public.auto_trade_risk_counters;
create policy atrc_owner_insert on public.auto_trade_risk_counters
  for insert with check (
    auth.uid() = user_id
    and exists (select 1 from public.trading_accounts a where a.id = account_id and a.user_id = auth.uid())
  );
drop policy if exists atrc_owner_update on public.auto_trade_risk_counters;
create policy atrc_owner_update on public.auto_trade_risk_counters
  for update using (auth.uid() = user_id) with check (auth.uid() = user_id);
