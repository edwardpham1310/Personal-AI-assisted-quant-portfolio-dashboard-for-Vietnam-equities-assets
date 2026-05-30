-- 0001_init.sql
--
-- Initial schema for the Quant VN Dashboard.
--   * 8 tables with PK/FK + indexes
--   * Triggers for updated_at and auto-profile-on-signup
--   * Row-Level Security on every table
--
-- Idempotent: safe to re-run on a fresh project.

set search_path = public;

-- =============================================================================
-- 1. profiles  (mirrors auth.users 1:1)
-- =============================================================================
create table if not exists public.profiles (
  id            uuid        primary key references auth.users(id) on delete cascade,
  email         text,
  display_name  text,
  created_at    timestamptz not null default now(),
  updated_at    timestamptz not null default now()
);

-- =============================================================================
-- 2. user_settings
-- =============================================================================
create table if not exists public.user_settings (
  id                    uuid        primary key default gen_random_uuid(),
  user_id               uuid        not null unique references auth.users(id) on delete cascade,
  default_broker        text        not null default 'SSI',
  risk_profile          text        not null default 'moderate'
                                     check (risk_profile in ('conservative', 'moderate', 'aggressive')),
  default_watchlist_id  uuid,
  theme                 text        not null default 'dark' check (theme in ('dark', 'light')),
  created_at            timestamptz not null default now(),
  updated_at            timestamptz not null default now()
);

-- =============================================================================
-- 3. watchlists
-- =============================================================================
create table if not exists public.watchlists (
  id          uuid        primary key default gen_random_uuid(),
  user_id     uuid        not null references auth.users(id) on delete cascade,
  name        text        not null,
  description text,
  created_at  timestamptz not null default now(),
  updated_at  timestamptz not null default now()
);
create index if not exists idx_watchlists_user on public.watchlists(user_id);

-- Soft FK from user_settings.default_watchlist_id (no cascade — just nullify).
alter table public.user_settings
  drop constraint if exists user_settings_default_watchlist_fkey;
alter table public.user_settings
  add constraint user_settings_default_watchlist_fkey
  foreign key (default_watchlist_id) references public.watchlists(id) on delete set null;

-- =============================================================================
-- 4. watchlist_items
-- =============================================================================
create table if not exists public.watchlist_items (
  id            uuid        primary key default gen_random_uuid(),
  watchlist_id  uuid        not null references public.watchlists(id) on delete cascade,
  symbol        text        not null,
  exchange      text        not null default 'HOSE' check (exchange in ('HOSE', 'HNX', 'UPCOM')),
  display_order integer     not null default 0,
  created_at    timestamptz not null default now(),
  unique (watchlist_id, symbol)
);
create index if not exists idx_watchlist_items_watchlist on public.watchlist_items(watchlist_id);

-- =============================================================================
-- 5. manual_portfolio_accounts
-- =============================================================================
create table if not exists public.manual_portfolio_accounts (
  id         uuid        primary key default gen_random_uuid(),
  user_id    uuid        not null references auth.users(id) on delete cascade,
  name       text        not null,
  broker     text        not null default 'SSI',
  currency   text        not null default 'VND',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create index if not exists idx_manual_accounts_user on public.manual_portfolio_accounts(user_id);

-- =============================================================================
-- 6. manual_positions
-- =============================================================================
create table if not exists public.manual_positions (
  id            uuid           primary key default gen_random_uuid(),
  account_id    uuid           not null references public.manual_portfolio_accounts(id) on delete cascade,
  symbol        text           not null,
  exchange      text           not null default 'HOSE' check (exchange in ('HOSE', 'HNX', 'UPCOM')),
  quantity      integer        not null check (quantity > 0),
  avg_cost      numeric(20, 4) not null check (avg_cost >= 0),
  strategy_tag  text,
  note          text,
  created_at    timestamptz    not null default now(),
  updated_at    timestamptz    not null default now()
);
create index if not exists idx_manual_positions_account on public.manual_positions(account_id);

-- =============================================================================
-- 7. recommendation_snapshots  (append-only event log; written by backend jobs)
-- =============================================================================
create table if not exists public.recommendation_snapshots (
  id          uuid         primary key default gen_random_uuid(),
  user_id     uuid         not null references auth.users(id) on delete cascade,
  symbol      text         not null,
  horizon     text         not null check (horizon in ('INTRADAY_5M', 'INTRADAY_15M', 'EOD')),
  action      text         not null check (action in ('BUY', 'SELL', 'HOLD', 'REDUCE')),
  confidence  numeric(5,4) check (confidence is null or (confidence >= 0 and confidence <= 1)),
  status      text         not null default 'OPEN'
                            check (status in ('OPEN', 'ACKED', 'DISMISSED', 'EXPIRED')),
  reasons     jsonb        not null default '[]'::jsonb,
  warnings    jsonb        not null default '[]'::jsonb,
  scores      jsonb        not null default '{}'::jsonb,
  created_at  timestamptz  not null default now()
);
create index if not exists idx_reco_user_created
  on public.recommendation_snapshots(user_id, created_at desc);

-- =============================================================================
-- 8. security_audit_logs (append-only; written by backend)
-- =============================================================================
create table if not exists public.security_audit_logs (
  id         uuid        primary key default gen_random_uuid(),
  user_id    uuid        references auth.users(id) on delete set null,
  action     text        not null,
  metadata   jsonb       not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);
create index if not exists idx_audit_user_created
  on public.security_audit_logs(user_id, created_at desc);

-- =============================================================================
-- Trigger: keep updated_at fresh
-- =============================================================================
create or replace function public.set_updated_at()
returns trigger language plpgsql as $$
begin
  new.updated_at := now();
  return new;
end;
$$;

drop trigger if exists profiles_set_updated_at on public.profiles;
create trigger profiles_set_updated_at before update on public.profiles
  for each row execute function public.set_updated_at();

drop trigger if exists user_settings_set_updated_at on public.user_settings;
create trigger user_settings_set_updated_at before update on public.user_settings
  for each row execute function public.set_updated_at();

drop trigger if exists watchlists_set_updated_at on public.watchlists;
create trigger watchlists_set_updated_at before update on public.watchlists
  for each row execute function public.set_updated_at();

drop trigger if exists manual_accounts_set_updated_at on public.manual_portfolio_accounts;
create trigger manual_accounts_set_updated_at before update on public.manual_portfolio_accounts
  for each row execute function public.set_updated_at();

drop trigger if exists manual_positions_set_updated_at on public.manual_positions;
create trigger manual_positions_set_updated_at before update on public.manual_positions
  for each row execute function public.set_updated_at();

-- =============================================================================
-- Trigger: auto-provision profile + settings on new auth.users row
-- =============================================================================
create or replace function public.handle_new_user()
returns trigger language plpgsql security definer as $$
begin
  insert into public.profiles (id, email, display_name)
    values (
      new.id,
      new.email,
      coalesce(new.raw_user_meta_data->>'display_name', split_part(new.email, '@', 1))
    )
    on conflict (id) do nothing;

  insert into public.user_settings (user_id) values (new.id)
    on conflict (user_id) do nothing;

  return new;
end;
$$;

drop trigger if exists on_auth_user_created on auth.users;
create trigger on_auth_user_created
  after insert on auth.users
  for each row execute function public.handle_new_user();

-- =============================================================================
-- RLS — enable on every table
-- =============================================================================
alter table public.profiles                  enable row level security;
alter table public.user_settings             enable row level security;
alter table public.watchlists                enable row level security;
alter table public.watchlist_items           enable row level security;
alter table public.manual_portfolio_accounts enable row level security;
alter table public.manual_positions          enable row level security;
alter table public.recommendation_snapshots  enable row level security;
alter table public.security_audit_logs      enable row level security;

-- ---- profiles ---------------------------------------------------------------
drop policy if exists profiles_select on public.profiles;
create policy profiles_select on public.profiles
  for select using (id = auth.uid());

drop policy if exists profiles_insert on public.profiles;
create policy profiles_insert on public.profiles
  for insert with check (id = auth.uid());

drop policy if exists profiles_update on public.profiles;
create policy profiles_update on public.profiles
  for update using (id = auth.uid()) with check (id = auth.uid());

-- ---- user_settings ----------------------------------------------------------
drop policy if exists user_settings_owner on public.user_settings;
create policy user_settings_owner on public.user_settings
  for all using (user_id = auth.uid()) with check (user_id = auth.uid());

-- ---- watchlists -------------------------------------------------------------
drop policy if exists watchlists_owner on public.watchlists;
create policy watchlists_owner on public.watchlists
  for all using (user_id = auth.uid()) with check (user_id = auth.uid());

-- ---- watchlist_items (parent-owned) -----------------------------------------
drop policy if exists watchlist_items_owner on public.watchlist_items;
create policy watchlist_items_owner on public.watchlist_items
  for all using (
    exists (select 1 from public.watchlists w
            where w.id = watchlist_items.watchlist_id and w.user_id = auth.uid())
  )
  with check (
    exists (select 1 from public.watchlists w
            where w.id = watchlist_items.watchlist_id and w.user_id = auth.uid())
  );

-- ---- manual_portfolio_accounts ----------------------------------------------
drop policy if exists manual_accounts_owner on public.manual_portfolio_accounts;
create policy manual_accounts_owner on public.manual_portfolio_accounts
  for all using (user_id = auth.uid()) with check (user_id = auth.uid());

-- ---- manual_positions (parent-owned) ----------------------------------------
drop policy if exists manual_positions_owner on public.manual_positions;
create policy manual_positions_owner on public.manual_positions
  for all using (
    exists (select 1 from public.manual_portfolio_accounts a
            where a.id = manual_positions.account_id and a.user_id = auth.uid())
  )
  with check (
    exists (select 1 from public.manual_portfolio_accounts a
            where a.id = manual_positions.account_id and a.user_id = auth.uid())
  );

-- ---- recommendation_snapshots (user reads own; writes via service_role) ----
drop policy if exists reco_select on public.recommendation_snapshots;
create policy reco_select on public.recommendation_snapshots
  for select using (user_id = auth.uid());

drop policy if exists reco_update on public.recommendation_snapshots;
create policy reco_update on public.recommendation_snapshots
  for update using (user_id = auth.uid()) with check (user_id = auth.uid());
-- (No INSERT policy: only service_role can write, which bypasses RLS.)

-- ---- security_audit_logs (user reads own; writes via service_role) ---------
drop policy if exists audit_select on public.security_audit_logs;
create policy audit_select on public.security_audit_logs
  for select using (user_id = auth.uid());
-- (No INSERT/UPDATE/DELETE policy: only service_role.)
