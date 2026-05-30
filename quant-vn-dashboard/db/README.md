# db/

SQL migrations for the Supabase Postgres app schema. Run these in your
Supabase project's SQL Editor (or via the Supabase CLI) **in order**.

## Apply

### Via the Supabase Dashboard
1. Open your project → SQL Editor → New query.
2. Paste the contents of `migrations/0001_init.sql` and run.

### Via the Supabase CLI
```bash
supabase db push
# or, for ad-hoc:
supabase db execute --file db/migrations/0001_init.sql
```

## Local development

For end-to-end local testing, use the Supabase CLI:
```bash
supabase init
supabase start
# Apply migrations:
supabase db reset           # destructive, only on dev
```

Connection details (`SUPABASE_URL`, `SUPABASE_ANON_KEY`, `SUPABASE_SERVICE_ROLE_KEY`,
`SUPABASE_JWT_SECRET`) are printed by `supabase start`. Copy them into the
monorepo `.env`.

## Schema

| Table                       | Purpose                                          |
| --------------------------- | ------------------------------------------------ |
| `profiles`                  | 1:1 with `auth.users`, auto-created on signup.   |
| `user_settings`             | Per-user preferences (broker, theme, default WL).|
| `watchlists`                | User-owned named lists of symbols.               |
| `watchlist_items`           | Symbols inside a watchlist.                      |
| `manual_portfolio_accounts` | User-managed accounts (not synced from broker).  |
| `manual_positions`          | Positions inside a manual account.               |
| `recommendation_snapshots`  | Append-only stream of generated recommendations. |
| `security_audit_logs`       | Append-only audit trail of sensitive actions.    |

Every table enables **Row-Level Security**. Policies require
`auth.uid() = user_id` (directly or via the parent table). The Supabase
`service_role` bypasses RLS — used **only** by trusted backend jobs.
