# Auth Flow

The dashboard uses **Supabase Auth** for user identity and **Supabase Postgres
with Row-Level Security** for app data.

```
 ┌─────────┐         email+password           ┌───────────────┐
 │ Browser │ ───────────────────────────────▶ │ Supabase Auth │
 └────┬────┘                                   └──────┬────────┘
      │       JWT + refresh token in cookies          │
      │ ◀─────────────────────────────────────────────┘
      │
      │  Bearer <jwt>      ┌─────────────────┐
      ├───────────────────▶│ FastAPI         │
      │                    │ (verifies JWT   │
      │                    │  with HS256)    │
      │                    └──────┬──────────┘
      │                           │ user JWT, anon key
      │                           ▼
      │                    ┌─────────────────┐
      │                    │ PostgREST + RLS │
      │                    └─────────────────┘
```

## Step by step

1. **Sign in / sign up** — the `/login` page uses `@supabase/ssr`'s browser
   client to call `signInWithPassword` or `signUp`. On success Supabase sets
   session cookies (`sb-…-auth-token`) that survive page reloads.
2. **Middleware refresh** — every request hits `apps/web/src/middleware.ts`,
   which calls `updateSession()` to refresh the access token if needed. If
   the user is not authenticated and the path is not `/login` or `/auth/*`,
   the user is bounced to `/login?redirectTo=<original>`.
3. **Browser → FastAPI** — `useApi()` reads `session.access_token` from the
   Supabase client and adds `Authorization: Bearer <jwt>` to every request.
4. **FastAPI verification** — `core/security.py::get_current_user` reads the
   header, validates the JWT signature with HS256 using `SUPABASE_JWT_SECRET`,
   checks the audience claim (`authenticated`), and exposes an `AuthContext`
   with the verified `user_id`, `email`, and the raw token.
5. **FastAPI → PostgREST** — `services/supabase_db.py` calls Supabase
   PostgREST using the **user's JWT** + the **anon key**. RLS evaluates each
   policy against `auth.uid()` and enforces ownership.
6. **Never trust client-supplied user_id** — every route derives identity
   from the JWT. Routes that need to write a `user_id` column always use
   `current_user.user_id` from the verified context.

## Key invariants

| Invariant                                | Where enforced                          |
| ---------------------------------------- | --------------------------------------- |
| JWT signature is verified before use     | `core.security.verify_supabase_jwt`     |
| Frontend never sees `SUPABASE_SERVICE_ROLE_KEY` | `apps/web/src/lib/env.ts` exposes only NEXT_PUBLIC_* |
| Cross-user reads/writes are impossible   | RLS policies in `db/migrations/0001_init.sql` |
| Sign-out drops session cookies           | `supabase.auth.signOut()` in `UserMenu` |
| Unauthenticated users can't reach dashboard | Next.js `middleware.ts` redirects to /login |

## Service role usage

`SUPABASE_SERVICE_ROLE_KEY` is **only** used by backend jobs that need to
bypass RLS — e.g. writing `recommendation_snapshots` from the analytics
worker. It is never sent in response to a user request and never passed to
the browser.

## Local development

1. Start Supabase locally:
   ```bash
   supabase start
   ```
2. Apply migrations:
   ```bash
   supabase db reset            # destructive: only on a fresh dev DB
   # or:
   psql "$DATABASE_URL" -f db/migrations/0001_init.sql
   ```
3. Copy the printed URL + keys into `.env`:
   - `NEXT_PUBLIC_SUPABASE_URL`, `NEXT_PUBLIC_SUPABASE_ANON_KEY` — for the web
   - `SUPABASE_URL`, `SUPABASE_ANON_KEY`, `SUPABASE_SERVICE_ROLE_KEY`,
     `SUPABASE_JWT_SECRET`, `SUPABASE_DB_PASSWORD`, `DATABASE_URL` — for the API
4. Create a test user from the Supabase Studio (or `supabase auth users create`).
5. `make dev-api` and `make dev-web`, then sign in at <http://localhost:3000/login>.
