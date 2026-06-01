"use client";

import { useApi } from "@/lib/api";
import { usePollingResource } from "./usePollingResource";

// Phase 2.5 codes — CONNECTED preferred, READY/PROVIDER_ERROR kept for
// back-compat with cached snapshots.
export type ProviderStatusCode =
  | "CONNECTED"
  | "READY"
  | "CONFIG_MISSING"
  | "AUTH_FAILED"
  | "RATE_LIMITED"
  | "ERROR"
  | "PROVIDER_ERROR"
  | "STALE";

export type ProviderMode = "REAL" | "MOCK_TEST_ONLY";

export type TokenStatus = "VALID" | "EXPIRED" | "MISSING" | "UNKNOWN";

export type ProviderHealth = {
  name: string;
  ready: boolean;
  mock: boolean;
  token_cached: boolean;
  last_call_ts: string | null;
  note: string | null;
  error: string | null;
  // Phase 2.5 additions — UI uses these for color-coded badges + the
  // critical production-mock banner.
  status_code?: ProviderStatusCode;
  mode?: ProviderMode;
  last_successful_call_at?: string | null;
  last_failed_call_at?: string | null;
  last_error_sanitized?: string | null;
  token_status?: TokenStatus;
  production_ready?: boolean;
};

export type CacheHealth = {
  name: string;
  configured: boolean;
  healthy: boolean;
  last_poll_ts: string | null;
  last_poll_ok: boolean | null;
  last_poll_error: string | null;
  error: string | null;
};

export type SupabaseHealth = {
  configured: boolean;
  url_host: string | null;
};

export type DuckDBHealth = {
  configured: boolean;
  path: string | null;
  exists: boolean;
  size_bytes: number | null;
};

export type PollerHealth = {
  enabled: boolean;
  running: boolean;
  active_symbols_count: number;
};

export type StaleQuoteRow = {
  symbol: string;
  ts: string;
  age_seconds: number;
  stale: boolean;
  source: string;
};

export type DataQualitySnapshot = {
  timestamp: string;
  stale_quote_count: number;
  total_tracked_symbols: number;
  symbols_without_quote: string[];
  stale_quote_rows: StaleQuoteRow[];
  cache_misses: number | null;
  provider_errors: number | null;
  last_successful_sync: string | null;
  notes: string[];
};

export type SystemStatus = {
  app_env: string;
  missing_secrets: string[];
  ssi_base_url: string;
  redis_configured: boolean;
  provider: ProviderHealth;
  cache: CacheHealth;
  supabase: SupabaseHealth;
  duckdb: DuckDBHealth;
  poller: PollerHealth;
  data_quality: DataQualitySnapshot;
  checked_at: string;
};

const POLL_INTERVAL_MS = 60_000;

export function useSystemStatus() {
  const api = useApi();
  return usePollingResource<SystemStatus>({
    fetcher: () => api<SystemStatus>("/system/status"),
    intervalMs: POLL_INTERVAL_MS,
  });
}
