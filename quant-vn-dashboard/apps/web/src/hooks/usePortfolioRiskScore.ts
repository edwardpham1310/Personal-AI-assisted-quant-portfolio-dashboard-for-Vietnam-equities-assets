"use client";

import { useApi } from "@/lib/api";
import { usePollingResource } from "./usePollingResource";

export type RiskComponent = {
  key: string;
  label: string;
  available: boolean;
  score?: number | null;
  weight: number;
  detail?: string | null;
  reason?: string | null;
};

export type RiskScore = {
  score: number | null;
  band: string;
  components: RiskComponent[];
  available_count: number;
  total_count: number;
  as_of?: string | null;
  disclaimer?: string;
};

const POLL_MS = 60_000;

/**
 * GET /portfolio/risk-score — explainable, read-only, partial-aware portfolio
 * risk score. ``score`` is null when nothing can be computed (e.g. no
 * positions); individual components carry availability + an explanation. No
 * trading; no fabricated numbers.
 */
export function usePortfolioRiskScore() {
  const api = useApi();
  const resource = usePollingResource<RiskScore>({
    fetcher: () => api<RiskScore>("/portfolio/risk-score"),
    intervalMs: POLL_MS,
  });
  return {
    data: resource.data,
    loading: resource.loading,
    error: resource.error,
    refresh: resource.refresh,
  };
}
