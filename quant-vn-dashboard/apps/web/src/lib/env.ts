/**
 * Public env vars consumed by the browser. Only NEXT_PUBLIC_* values may appear
 * here — never inline a server-only secret.
 */

const RAW_API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";
const APP_ENV = process.env.NEXT_PUBLIC_APP_ENV ?? "development";

function isLocalhostUrl(url: string): boolean {
  return /^https?:\/\/(localhost|127\.0\.0\.1)(:\d+)?(\/|$)/.test(url);
}

export const env = {
  /**
   * Base URL for every apps/api request. Guarded so a production bundle can
   * NEVER silently fall back to localhost: when NEXT_PUBLIC_APP_ENV=production
   * and the URL is missing or points at localhost, reading this throws loudly
   * instead of quietly calling a dead host. Evaluated lazily (getter) so a
   * correctly-configured production build/SSG pass is never blocked — the
   * error only surfaces on the genuine misconfiguration.
   */
  get apiBaseUrl(): string {
    if (APP_ENV === "production" && isLocalhostUrl(RAW_API_BASE_URL)) {
      throw new Error(
        "[env] NEXT_PUBLIC_API_BASE_URL is missing or points at localhost in a " +
          "production build. Set it to the production API origin (https://…).",
      );
    }
    return RAW_API_BASE_URL;
  },
  supabaseUrl: process.env.NEXT_PUBLIC_SUPABASE_URL ?? "",
  supabaseAnonKey: process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY ?? "",
  appEnv: APP_ENV,
};

/** True when the bundle was built with NEXT_PUBLIC_APP_ENV=production.
 *  Hooks rely on this to refuse silent mock-fallback substitution. */
export const isProductionBuild = env.appEnv === "production";
