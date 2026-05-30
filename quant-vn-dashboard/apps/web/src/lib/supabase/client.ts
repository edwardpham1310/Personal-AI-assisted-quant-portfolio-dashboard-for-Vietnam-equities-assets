import { createBrowserClient } from "@supabase/ssr";
import { env } from "../env";

/**
 * Supabase client for use in Client Components and browser-side hooks.
 * Reads the anon key only — service-role key never crosses this boundary.
 */
export function createClient() {
  return createBrowserClient(env.supabaseUrl, env.supabaseAnonKey);
}
