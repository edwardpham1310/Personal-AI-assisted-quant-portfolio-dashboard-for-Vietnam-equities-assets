"use client";

import { useApi } from "@/lib/api";
import { usePollingResource } from "./usePollingResource";

/** GET /market/regime — VNINDEX 4-state trend heuristic (30/50/60/80). */
export type MarketRegime = {
  score: number;
  label: string; // "UPTREND" | "MIXED" | "DOWNTREND" | "NO_DATA"
  data_status: string;
  bars_used: number;
  as_of: string | null;
};

const POLL_MS = 60_000;

export function useMarketRegime() {
  const api = useApi();
  const resource = usePollingResource<MarketRegime>({
    fetcher: () => api<MarketRegime>("/market/regime"),
    intervalMs: POLL_MS,
  });
  return { data: resource.data, loading: resource.loading, error: resource.error };
}
