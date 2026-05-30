"use client";

import { useApi } from "@/lib/api";
import { usePollingResource } from "./usePollingResource";
import type { EnrichedPosition } from "./portfolio-types";

const POLL_MS = 60_000;

/**
 * Polls ``GET /portfolio/positions`` every 60 seconds while the tab is
 * visible. Returns positions enriched with last marked price, market value,
 * and unrealized PnL.
 */
export function usePortfolioPositions() {
  const api = useApi();
  const resource = usePollingResource<EnrichedPosition[]>({
    fetcher: () => api<EnrichedPosition[]>("/portfolio/positions"),
    intervalMs: POLL_MS,
  });
  return {
    positions: resource.data ?? [],
    loading: resource.loading,
    error: resource.error,
    refresh: resource.refresh,
  };
}
