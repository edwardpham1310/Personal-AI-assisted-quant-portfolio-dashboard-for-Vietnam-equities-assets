-- 0012_reco_reference_price.sql
--
-- Feature 5 (Recommendation History + Performance) needs a price reference
-- captured AT recommendation time so a later performance view can compute an
-- honest, hypothetical return (reference_price -> current quote) without
-- pretending the user actually traded.
--
-- recommendation_snapshots stores entry_zone/stop/take_profit but never the
-- mark price at the moment the signal was generated. This adds it. Nullable so
-- older rows (and rows where the quote was unavailable) stay valid; the
-- performance endpoint skips rows with no reference_price. Idempotent.

set search_path = public;

alter table public.recommendation_snapshots
  add column if not exists reference_price numeric(20, 4);

-- No RLS change: reco_select / reco_insert / reco_update already scope the
-- table to the owning user (0001_init.sql + 0004_reco_insert_policy.sql).
