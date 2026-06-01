"use client";

import { useCallback } from "react";
import { createClient } from "./supabase/client";
import { env } from "./env";

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly detail: string,
  ) {
    super(detail);
  }
}

/**
 * Browser-side fetch wrapper. Pulls the Supabase access token from the
 * current session and adds it to `Authorization`. Returns parsed JSON or
 * throws `ApiError` carrying the FastAPI `detail` payload.
 */
export function useApi() {
  return useCallback(async <T = unknown>(path: string, init: RequestInit = {}): Promise<T> => {
    const supabase = createClient();
    const {
      data: { session },
    } = await supabase.auth.getSession();
    const token = session?.access_token;

    const headers = new Headers(init.headers);
    headers.set("Content-Type", "application/json");
    if (token) headers.set("Authorization", `Bearer ${token}`);

    const res = await fetch(`${env.apiBaseUrl}${path}`, { ...init, headers });

    if (res.status === 204) return undefined as T;

    if (!res.ok) {
      let detail = res.statusText;
      try {
        const body = (await res.json()) as { detail?: string };
        detail = body.detail ?? detail;
      } catch {
        /* non-JSON body */
      }
      throw new ApiError(res.status, detail);
    }
    return (await res.json()) as T;
  }, []);
}
