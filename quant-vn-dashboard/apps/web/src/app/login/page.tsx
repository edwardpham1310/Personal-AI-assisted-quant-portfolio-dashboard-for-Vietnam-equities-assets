"use client";

import { Suspense, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import type { Route } from "next";
import { createClient } from "@/lib/supabase/client";

/**
 * Validate the ``?redirectTo=`` query param.
 *
 * Next.js' ``experimental.typedRoutes`` rejects generic ``string`` values to
 * ``router.push``. We accept only same-origin paths starting with ``/`` and
 * fall back to ``/dashboard``, then assert the result as ``Route`` since the
 * runtime guarantee matches what typed-routes wants statically.
 */
function safeRedirectTo(raw: string | null): Route {
  if (raw && raw.startsWith("/") && !raw.startsWith("//")) {
    return raw as Route;
  }
  return "/dashboard" as Route;
}

type Mode = "signin" | "signup";

function LoginForm() {
  const router = useRouter();
  const params = useSearchParams();
  const redirectTo = safeRedirectTo(params.get("redirectTo"));

  const [mode, setMode] = useState<Mode>("signin");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [info, setInfo] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setInfo(null);
    setLoading(true);
    try {
      const supabase = createClient();
      if (mode === "signin") {
        const { error: e1 } = await supabase.auth.signInWithPassword({
          email,
          password,
        });
        if (e1) throw e1;
        router.push(redirectTo);
        router.refresh();
      } else {
        const { error: e2 } = await supabase.auth.signUp({ email, password });
        if (e2) throw e2;
        setInfo("Check your email to confirm the account, then sign in below.");
        setMode("signin");
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Authentication failed.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="min-h-screen flex items-center justify-center bg-bg p-6">
      <form
        onSubmit={submit}
        className="w-full max-w-sm rounded-lg border border-border bg-bg-panel p-6 space-y-4"
      >
        <header>
          <h1 className="text-lg font-semibold text-ink">Quant VN Dashboard</h1>
          <p className="text-xs text-ink-dim mt-1">
            {mode === "signin" ? "Sign in to continue." : "Create an account."}
          </p>
        </header>

        <label className="block">
          <span className="text-xs text-ink-muted">Email</span>
          <input
            type="email"
            required
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            autoComplete="email"
            className="mt-1 w-full rounded border border-border bg-bg px-3 py-2 text-sm text-ink outline-none focus:border-accent"
          />
        </label>

        <label className="block">
          <span className="text-xs text-ink-muted">Password</span>
          <input
            type="password"
            required
            minLength={8}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoComplete={mode === "signin" ? "current-password" : "new-password"}
            className="mt-1 w-full rounded border border-border bg-bg px-3 py-2 text-sm text-ink outline-none focus:border-accent"
          />
        </label>

        {info ? <p className="text-xs text-accent-up">{info}</p> : null}
        {error ? <p className="text-xs text-accent-down">{error}</p> : null}

        <button
          type="submit"
          disabled={loading}
          className="w-full rounded bg-accent px-3 py-2 text-sm font-medium text-white hover:opacity-90 disabled:opacity-50"
        >
          {loading ? "Working…" : mode === "signin" ? "Sign in" : "Create account"}
        </button>

        <button
          type="button"
          onClick={() => {
            setMode(mode === "signin" ? "signup" : "signin");
            setError(null);
            setInfo(null);
          }}
          className="block w-full text-center text-xs text-ink-muted hover:text-ink"
        >
          {mode === "signin"
            ? "Don’t have an account? Create one"
            : "Already have an account? Sign in"}
        </button>
      </form>
    </main>
  );
}

export default function LoginPage() {
  return (
    <Suspense fallback={null}>
      <LoginForm />
    </Suspense>
  );
}
