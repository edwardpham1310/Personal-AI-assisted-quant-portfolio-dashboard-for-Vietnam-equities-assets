-- 0003_recommendations_extend.sql
--
-- Recommendation engine MVP — extend recommendation_snapshots so it can
-- store the broader profile/horizon/action vocabulary and trade-plan
-- numbers produced by services/recommendation_engine.py.
--
-- Keeps legacy values for back-compat. Idempotent.

set search_path = public;

-- =============================================================================
-- 1. CHECK constraints — drop existing restrictive ones, add expanded ones
-- =============================================================================

-- Horizon: original allowed only intraday + EOD. Now allow short/long codes
-- emitted by the engine alongside the legacy intraday/EOD values.
alter table public.recommendation_snapshots
  drop constraint if exists recommendation_snapshots_horizon_check;
alter table public.recommendation_snapshots
  add constraint recommendation_snapshots_horizon_check
  check (horizon in (
    'SHORT_T3',
    'SHORT_1W',
    'SHORT_2W',
    'SHORT_1M',
    'LONG_3M',
    'LONG_6M',
    'LONG_12M',
    'INTRADAY_5M',
    'INTRADAY_15M',
    'EOD'
  ));

-- Action: original allowed only BUY/SELL/HOLD/REDUCE. Expand to the engine
-- vocabulary plus REJECTED (guardrail outcome) and keep BUY/SELL legacy too.
alter table public.recommendation_snapshots
  drop constraint if exists recommendation_snapshots_action_check;
alter table public.recommendation_snapshots
  add constraint recommendation_snapshots_action_check
  check (action in (
    'BUY_CANDIDATE',
    'WATCH',
    'HOLD',
    'REDUCE',
    'SELL_CANDIDATE',
    'AVOID',
    'REJECTED',
    'BUY',
    'SELL'
  ));

-- =============================================================================
-- 2. Engine columns — trade-plan numbers + as_of snapshot timestamp
-- =============================================================================
alter table public.recommendation_snapshots
  add column if not exists profile text;

alter table public.recommendation_snapshots
  add column if not exists entry_zone_low numeric(20, 4);

alter table public.recommendation_snapshots
  add column if not exists entry_zone_high numeric(20, 4);

alter table public.recommendation_snapshots
  add column if not exists stop_loss numeric(20, 4);

alter table public.recommendation_snapshots
  add column if not exists take_profit_1 numeric(20, 4);

alter table public.recommendation_snapshots
  add column if not exists take_profit_2 numeric(20, 4);

alter table public.recommendation_snapshots
  add column if not exists position_size_vnd bigint;

alter table public.recommendation_snapshots
  add column if not exists estimated_quantity integer;

alter table public.recommendation_snapshots
  add column if not exists estimated_total_cost bigint;

alter table public.recommendation_snapshots
  add column if not exists as_of timestamptz;

-- =============================================================================
-- 3. RLS — already enabled in 0001_init.sql. Policies (reco_select / reco_update)
-- are preserved; writes still flow through service_role which bypasses RLS.
-- No policy changes needed here.
-- =============================================================================
