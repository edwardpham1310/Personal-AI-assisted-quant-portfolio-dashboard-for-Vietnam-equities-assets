import { createServerClient, type CookieOptions } from "@supabase/ssr";
import { cookies } from "next/headers";
import { env } from "../env";

type CookieRecord = { name: string; value: string; options?: CookieOptions };

/**
 * Supabase client for use in Server Components and Route Handlers.
 *
 * Reads the session cookie set by the middleware. Cookies are async in
 * Next 15 — `await createClient()` before calling.
 */
export async function createClient() {
  const cookieStore = await cookies();
  return createServerClient(env.supabaseUrl, env.supabaseAnonKey, {
    cookies: {
      getAll() {
        return cookieStore.getAll();
      },
      setAll(cookiesToSet: CookieRecord[]) {
        try {
          cookiesToSet.forEach(({ name, value, options }) => cookieStore.set(name, value, options));
        } catch {
          // Server Components cannot set cookies; the middleware handles it.
        }
      },
    },
  });
}
