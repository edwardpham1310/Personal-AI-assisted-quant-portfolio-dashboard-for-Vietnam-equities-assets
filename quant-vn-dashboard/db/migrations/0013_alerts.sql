-- 0013_alerts.sql
--
-- Feature 6 (Alerts) — user-defined research notification rules. An alert is a
-- price/percent-change threshold on a symbol; it NEVER places an order. The
-- backend evaluates alerts against the latest cached quote on read; this table
-- only stores the rule + an optional last_triggered_at the user can manage.
--
-- RLS: owner-only, same pattern as watchlists. Idempotent.

set search_path = public;

create table if not exists public.alerts (
  id                uuid        primary key default gen_random_uuid(),
  user_id           uuid        not null references auth.users(id) on delete cascade,
  symbol            text        not null,
  exchange          text        not null default 'HOSE'
                                check (exchange in ('HOSE', 'HNX', 'UPCOM')),
  condition         text        not null
                                check (condition in (
                                  'price_above',
                                  'price_below',
                                  'pct_change_above',
                                  'pct_change_below'
                                )),
  -- threshold unit matches the condition: a price (VND) for price_*; a daily
  -- change FRACTION (0.03 = +3%) for pct_change_*.
  threshold         numeric(20, 6) not null,
  note              text,
  is_active         boolean     not null default true,
  last_triggered_at timestamptz,
  created_at        timestamptz not null default now(),
  updated_at        timestamptz not null default now()
);
create index if not exists idx_alerts_user on public.alerts(user_id);

alter table public.alerts enable row level security;

drop policy if exists alerts_owner on public.alerts;
create policy alerts_owner on public.alerts
  for all using (user_id = auth.uid()) with check (user_id = auth.uid());

drop trigger if exists alerts_set_updated_at on public.alerts;
create trigger alerts_set_updated_at before update on public.alerts
  for each row execute function public.set_updated_at();
