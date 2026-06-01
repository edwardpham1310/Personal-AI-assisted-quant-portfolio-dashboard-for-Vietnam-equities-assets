/**
 * Public env vars consumed by the browser. Only NEXT_PUBLIC_* values may appear
 * here — never inline a server-only secret.
 */
export const env = {
  apiBaseUrl: process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000",
  supabaseUrl: process.env.NEXT_PUBLIC_SUPABASE_URL ?? "",
  supabaseAnonKey: process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY ?? "",
  appEnv: process.env.NEXT_PUBLIC_APP_ENV ?? "development",
} as const;

/** True when the bundle was built with NEXT_PUBLIC_APP_ENV=production.
 *  Hooks rely on this to refuse silent mock-fallback substitution. */
export const isProductionBuild = env.appEnv === "production";
