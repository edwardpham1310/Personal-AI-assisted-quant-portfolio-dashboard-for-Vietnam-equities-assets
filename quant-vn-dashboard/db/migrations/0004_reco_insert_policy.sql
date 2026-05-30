-- 0004_reco_insert_policy.sql
--
-- Phase 1 review found that recommendation_snapshots had only `reco_select`
-- and `reco_update` policies (0001_init.sql:258-265). With RLS enabled and no
-- INSERT policy, every persist via a user JWT is silently rejected — the
-- recommendation engine's audit trail is therefore empty in practice.
--
-- This migration adds the missing INSERT policy. Idempotent.

set search_path = public;

drop policy if exists reco_insert on public.recommendation_snapshots;
create policy reco_insert on public.recommendation_snapshots
  for insert to authenticated
  with check (user_id = auth.uid());
