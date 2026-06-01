-- 0006_auto_trade_phase_2_6.sql
--
-- Phase 2.6 Auto-trade safety foundation.
--
-- Adds two tables:
--   * auto_trade_settings - one row per (user, trading_account); risk limits
--                            + allow-lists + last_reauth_at + risk_acknowledged_at.
--   * auto_trade_state    - one row per (user, trading_account); mode +
--                            is_running + emergency_stopped_at.
--
-- ``trading_audit_logs`` is reused from migration 0005 — Phase 2.6
-- writes ``action LIKE 'AUTO_TRADE_%'`` rows there.
--
-- All Phase 2.6 mode transitions write an audit row. ``trading_audit_logs``
-- already has the RLS owner_select + owner_insert policies in 0005.
--
-- Idempotent.

set search_path = public;

-- =============================================================================
-- 1. auto_trade_settings
-- =============================================================================
create table if not exists public.auto_trade_settings (
  id                       uuid        primary key default gen_random_uuid(),
  user_id                  uuid        not null references auth.users(id) on delete cascade,
  account_id               uuid        not null references public.trading_accounts(id) on delete cascade,
  mode                     text        not null default 'OFF'
                                       check (mode in ('OFF','PAPER_ONLY','LIVE_MANUAL_CONFIRM','LIVE_AUTO')),
  enabled                  boolean     not null default false,
  max_capital_vnd          numeric     not null default 0 check (max_capital_vnd >= 0),
  max_order_value_vnd      numeric     not null default 0 check (max_order_value_vnd >= 0),
  max_orders_per_day       integer     not null default 0 check (max_orders_per_day >= 0),
  max_daily_loss_vnd       numeric     not null default 0 check (max_daily_loss_vnd >= 0),
  max_position_weight      numeric     not null default 0 check (max_position_weight between 0 and 1),
  max_sector_weight        numeric     not null default 0 check (max_sector_weight between 0 and 1),
  allowed_strategies       jsonb       not null default '[]'::jsonb,
  allowed_symbols          jsonb       not null default '[]'::jsonb,
  allowed_watchlists       jsonb       not null default '[]'::jsonb,
  require_manual_confirm   boolean     not null default true,
  require_reauth           boolean     not null default true,
  last_reauth_at           timestamptz,
  risk_acknowledged_at     timestamptz,
  created_at               timestamptz not null default now(),
  updated_at               timestamptz not null default now(),
  unique (user_id, account_id)
);
create index if not exists auto_trade_settings_user_idx
  on public.auto_trade_settings(user_id);

alter table public.auto_trade_settings enable row level security;

drop policy if exists ats_owner_select on public.auto_trade_settings;
create policy ats_owner_select on public.auto_trade_settings
  for select using (auth.uid() = user_id);

drop policy if exists ats_owner_insert on public.auto_trade_settings;
create policy ats_owner_insert on public.auto_trade_settings
  for insert with check (
    auth.uid() = user_id
    and exists (
      select 1 from public.trading_accounts a
      where a.id = account_id and a.user_id = auth.uid()
    )
  );

drop policy if exists ats_owner_update on public.auto_trade_settings;
-- ``with check`` is critical: without it, an UPDATE could mutate
-- ``user_id`` to another value (the ``using`` clause only checks the
-- pre-image row). A crafted PATCH setting user_id=<victim> would
-- otherwise pass the using-clause and orphan the row to the victim.
create policy ats_owner_update on public.auto_trade_settings
  for update
    using (auth.uid() = user_id)
    with check (auth.uid() = user_id);

drop policy if exists ats_owner_delete on public.auto_trade_settings;
create policy ats_owner_delete on public.auto_trade_settings
  for delete using (auth.uid() = user_id);

-- =============================================================================
-- 2. auto_trade_state
-- =============================================================================
create table if not exists public.auto_trade_state (
  id                       uuid        primary key default gen_random_uuid(),
  user_id                  uuid        not null references auth.users(id) on delete cascade,
  account_id               uuid        not null references public.trading_accounts(id) on delete cascade,
  mode                     text        not null default 'OFF'
                                       check (mode in ('OFF','PAPER_ONLY','LIVE_MANUAL_CONFIRM','LIVE_AUTO')),
  is_running               boolean     not null default false,
  last_started_at          timestamptz,
  last_stopped_at          timestamptz,
  emergency_stopped_at     timestamptz,
  emergency_stop_reason    text,
  created_at               timestamptz not null default now(),
  updated_at               timestamptz not null default now(),
  unique (user_id, account_id)
);
create index if not exists auto_trade_state_user_idx
  on public.auto_trade_state(user_id);

alter table public.auto_trade_state enable row level security;

drop policy if exists astate_owner_select on public.auto_trade_state;
create policy astate_owner_select on public.auto_trade_state
  for select using (auth.uid() = user_id);

drop policy if exists astate_owner_insert on public.auto_trade_state;
create policy astate_owner_insert on public.auto_trade_state
  for insert with check (
    auth.uid() = user_id
    and exists (
      select 1 from public.trading_accounts a
      where a.id = account_id and a.user_id = auth.uid()
    )
  );

drop policy if exists astate_owner_update on public.auto_trade_state;
-- Same belt-and-suspenders as ``ats_owner_update`` above. The state row
-- is the runtime-truth row a future auto-trade executor reads — letting
-- it be re-assigned to another user is the worst-case row-takeover.
create policy astate_owner_update on public.auto_trade_state
  for update
    using (auth.uid() = user_id)
    with check (auth.uid() = user_id);
