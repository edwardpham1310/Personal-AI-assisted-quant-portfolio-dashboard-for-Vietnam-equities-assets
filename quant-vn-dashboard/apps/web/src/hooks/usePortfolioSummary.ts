"use client";

import { useApi } from "@/lib/api";
import { usePollingResource } from "./usePollingResource";
import type { PortfolioSummary } from "./portfolio-types";

const POLL_MS = 60_000;

/**
 * Polls ``GET /portfolio/summary`` every 60 seconds while the tab is visible.
 *
 * Returns the latest summary as well as a manual ``refresh`` callback for the
 * "Refresh" button. The summary is scoped to the user's default portfolio
 * account on the backend — the frontend doesn't pass an ``account_id``.
 */
export function usePortfolioSummary() {
  const api = useApi();
  const resource = usePollingResource<PortfolioSummary>({
    fetcher: () => api<PortfolioSummary>("/portfolio/summary"),
    intervalMs: POLL_MS,
  });
  return {
    summary: resource.data,
    loading: resource.loading,
    error: resource.error,
    refresh: resource.refresh,
  };
}
