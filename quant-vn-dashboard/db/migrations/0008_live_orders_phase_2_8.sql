-- 0008_live_orders_phase_2_8.sql
--
-- Phase 2.8 Manual-confirm live trading scaffold.
--
-- Tables:
--   * live_order_intents      — user-created intents, 8-state machine
--   * live_order_submissions  — one row per submit attempt (dry-run or live)
--
-- ``trading_audit_logs`` (from 0005) is reused for LIVE_ORDER_* actions.
--
-- All UPDATE policies use ``with check`` (lesson from prior reviews).
-- State-transition trigger on live_order_intents prevents direct
-- PostgREST status laundering — same hardening pattern as
-- paper_orders in 0007 (which itself was added by the Phase 2.7
-- review-fix cycle).
--
-- Idempotent.

set search_path = public;

-- =============================================================================
-- 1. live_order_intents
-- =============================================================================
create table if not exists public.live_order_intents (
  id                      uuid        primary key default gen_random_uuid(),
  user_id                 uuid        not null references auth.users(id) on delete cascade,
  account_id              uuid        not null references public.trading_accounts(id) on delete cascade,
  source_type             text        not null default 'MANUAL'
                                       check (source_type in ('MANUAL','RECOMMENDATION','PAPER_COPY','STRATEGY')),
  source_id               text,
  symbol                  text        not null,
  side                    text        not null check (side in ('BUY','SELL')),
  order_type              text        not null check (order_type in ('LIMIT','MARKET','ATO','ATC','MTL')),
  quantity                integer     not null check (quantity > 0),
  limit_price             numeric,
  preview_id              uuid,
  status                  text        not null default 'DRAFT'
                                       check (status in (
                                         'DRAFT','PREVIEWED','CONFIRM_REQUIRED',
                                         'CONFIRMED','SUBMITTED','REJECTED','CANCELLED','FAILED'
                                       )),
  validation_snapshot     jsonb,
  warnings                jsonb       not null default '[]'::jsonb,
  rejection_reasons       jsonb       not null default '[]'::jsonb,
  created_at              timestamptz not null default now(),
  confirmed_at            timestamptz,
  submitted_at            timestamptz,
  updated_at              timestamptz not null default now()
);
create index if not exists live_order_intents_user_idx on public.live_order_intents(user_id);
create index if not exists live_order_intents_acct_idx on public.live_order_intents(account_id, created_at desc);

alter table public.live_order_intents enable row level security;
drop policy if exists loi_owner_select on public.live_order_intents;
create policy loi_owner_select on public.live_order_intents
  for select using (auth.uid() = user_id);
drop policy if exists loi_owner_insert on public.live_order_intents;
create policy loi_owner_insert on public.live_order_intents
  for insert with check (
    auth.uid() = user_id
    and exists (select 1 from public.trading_accounts a where a.id = account_id and a.user_id = auth.uid())
  );
drop policy if exists loi_owner_update on public.live_order_intents;
create policy loi_owner_update on public.live_order_intents
  for update using (auth.uid() = user_id) with check (auth.uid() = user_id);

-- State-transition trigger. Mirrors paper_orders pattern from 0007 fix.
create or replace function public.check_live_order_intent_transition()
returns trigger as $$
begin
  if old.status = new.status then
    return new;
  end if;
  if old.status in ('SUBMITTED','REJECTED','CANCELLED','FAILED') then
    raise exception 'live_order_intents.status: cannot leave terminal state %', old.status;
  end if;
  if old.status = 'DRAFT'
     and new.status in ('PREVIEWED','REJECTED','CANCELLED') then
    return new;
  end if;
  if old.status = 'PREVIEWED'
     and new.status in ('CONFIRM_REQUIRED','PREVIEWED','REJECTED','CANCELLED') then
    return new;
  end if;
  if old.status = 'CONFIRM_REQUIRED'
     and new.status in ('CONFIRMED','REJECTED','CANCELLED') then
    return new;
  end if;
  if old.status = 'CONFIRMED'
     and new.status in ('SUBMITTED','REJECTED','CANCELLED','FAILED') then
    return new;
  end if;
  raise exception 'live_order_intents.status: illegal transition % → %', old.status, new.status;
end;
$$ language plpgsql;

drop trigger if exists live_order_intent_state_machine on public.live_order_intents;
create trigger live_order_intent_state_machine
  before update on public.live_order_intents
  for each row execute function public.check_live_order_intent_transition();

-- =============================================================================
-- 2. live_order_submissions
-- =============================================================================
create table if not exists public.live_order_submissions (
  id                              uuid        primary key default gen_random_uuid(),
  user_id                         uuid        not null references auth.users(id) on delete cascade,
  account_id                      uuid        not null references public.trading_accounts(id) on delete cascade,
  live_order_intent_id            uuid        not null references public.live_order_intents(id) on delete cascade,
  broker                          text        not null default 'SSI',
  broker_order_id                 text,
  request_payload_sanitized       jsonb       not null default '{}'::jsonb,
  response_payload_sanitized      jsonb       not null default '{}'::jsonb,
  status                          text        not null check (status in
                                    ('DRY_RUN_OK','LIVE_OK','REJECTED_BY_GATE','BROKER_ERROR')),
  submitted_at                    timestamptz not null default now(),
  created_at                      timestamptz not null default now()
);
create index if not exists los_intent_idx on public.live_order_submissions(live_order_intent_id);
create index if not exists los_user_idx on public.live_order_submissions(user_id, created_at desc);

alter table public.live_order_submissions enable row level security;
drop policy if exists los_owner_select on public.live_order_submissions;
create policy los_owner_select on public.live_order_submissions
  for select using (auth.uid() = user_id);
drop policy if exists los_owner_insert on public.live_order_submissions;
-- Strong INSERT policy: the referenced intent must belong to the same
-- user AND the same account. Prevents JWT-wielding client from fabricating
-- submission rows that reference another intent.
create policy los_owner_insert on public.live_order_submissions
  for insert with check (
    auth.uid() = user_id
    and exists (
      select 1 from public.live_order_intents i
      where i.id = live_order_intent_id
        and i.account_id = live_order_submissions.account_id
        and i.user_id = auth.uid()
    )
  );
-- No UPDATE/DELETE policy — submissions are immutable history.
