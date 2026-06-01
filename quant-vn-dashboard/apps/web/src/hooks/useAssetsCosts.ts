"use client";

import { useApi } from "@/lib/api";
import { usePollingResource } from "./usePollingResource";
import type { CostBreakdown, CostPeriod } from "./portfolio-types";

const POLL_MS = 60_000;

/**
 * Polls ``GET /assets/costs?period=…``. The ``period`` argument is part of
 * the dependency list so flipping MTD/YTD/ALL triggers an immediate refetch.
 */
export function useAssetsCosts(period: CostPeriod) {
  const api = useApi();
  const resource = usePollingResource<CostBreakdown>({
    fetcher: () => api<CostBreakdown>(`/assets/costs?period=${encodeURIComponent(period)}`),
    intervalMs: POLL_MS,
    deps: [period],
  });
  return {
    costs: resource.data,
    loading: resource.loading,
    error: resource.error,
    refresh: resource.refresh,
  };
}
