-- Migration 0010 — securities master + fundamentals
--
-- Background: SSI FastConnect Data exposes price/volume/index data
-- but NOT company fundamentals (ROE, net profit, audit opinion). The
-- guardrail upgrade (Phase 2.B) reads fundamentals through a separate
-- ``FundamentalDataProvider`` interface. The default DB-backed
-- implementation reads this table; the CSV implementation writes to
-- it via ``services.securities_sync``.
--
-- Reference data: not user-scoped. Anon role gets SELECT; writes
-- happen through the service role only (no insert/update/delete
-- policy is created intentionally).

create table if not exists public.securities (
    symbol                  text primary key,

    -- Master fields mirrored from SSI ``/api/v2/Market/Securities``.
    name                    text,
    exchange                text,
    type                    text,
    status                  text,
    board                   text,
    lot_size                int,
    reference_price         numeric,

    -- Fundamentals — populated by the operator's CSV upload or a
    -- future vendor integration. ``audit_opinion`` is one of
    -- {'UNQUALIFIED','QUALIFIED','ADVERSE','DISCLAIMER'} after
    -- normalisation by the provider; NULL means missing.
    market_cap              numeric,
    market_cap_source       text,
    listed_share            numeric,
    roe                     numeric,
    net_profit_last_4_quarters numeric[],   -- 4 elements, chronological
    audit_opinion           text,
    fiscal_period           text,           -- e.g. '2025-Q4'

    -- Index membership flags.
    is_vn30                 boolean default false,
    is_vn100                boolean default false,

    -- Provenance + freshness.
    fundamentals_source     text,           -- 'CSV' | 'WICHART' | 'FIIN' | ...
    fundamentals_as_of      date,
    last_synced_at          timestamptz default now()
);

create index if not exists securities_is_vn100_idx
    on public.securities (is_vn100) where is_vn100 = true;
create index if not exists securities_is_vn30_idx
    on public.securities (is_vn30) where is_vn30 = true;

-- RLS: anon reads, service-role writes.
alter table public.securities enable row level security;

drop policy if exists "securities_anon_select" on public.securities;
create policy "securities_anon_select" on public.securities
    for select using (true);

-- Intentionally no insert/update/delete policies — writes flow
-- through the service role and bypass RLS.

comment on table public.securities is
    'Per-symbol master row + fundamentals for the guardrail upgrade. '
    'SSI fields mirrored from /api/v2/Market/Securities; fundamentals '
    'fields populated by FundamentalDataProvider implementations.';
