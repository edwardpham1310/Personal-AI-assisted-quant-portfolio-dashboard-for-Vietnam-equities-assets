## Summary
<!-- 1-3 bullets: what changed and why -->

## Phase / Acceptance criteria
<!-- Link the AC this PR closes — Phase X.Y.Z or specific finding from a review report -->

## Safety surface touched
<!-- Tick any that apply -->
- [ ] Order placement / preview
- [ ] Auto-trade engine or worker tick
- [ ] Kill switch / emergency stop
- [ ] Re-auth / password gate
- [ ] SSI provider (data or trading)
- [ ] Audit log enum
- [ ] RLS policy or DB migration
- [ ] Secrets / env flags
- [ ] None of the above

## Test plan
- [ ] `cd apps/api && python3 -m pytest tests/ -q`
- [ ] `cd apps/web && npx tsc --noEmit && npm run lint && npm test -- --run`
- [ ] Manual verification: <describe>

## Risk + rollback
<!-- What breaks if this lands wrong? How do we roll back? -->
