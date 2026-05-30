"use client";

import { useApi } from "@/lib/api";
import { usePollingResource } from "./usePollingResource";
import type { AssetsSummary } from "./portfolio-types";

const POLL_MS = 60_000;

/**
 * Polls ``GET /assets/summary`` — settled cash, pending cash, T+2 advances,
 * MV, equity, buying power, withdrawable cash.
 */
export function useAssetsSummary() {
  const api = useApi();
  const resource = usePollingResource<AssetsSummary>({
    fetcher: () => api<AssetsSummary>("/assets/summary"),
    intervalMs: POLL_MS,
  });
  return {
    summary: resource.data,
    loading: resource.loading,
    error: resource.error,
    refresh: resource.refresh,
  };
}
