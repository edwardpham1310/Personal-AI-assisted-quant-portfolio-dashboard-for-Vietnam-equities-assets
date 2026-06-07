"use client";

import { useApi } from "@/lib/api";
import { usePollingResource } from "./usePollingResource";

export type TopPick = {
  symbol: string;
  company_name?: string | null;
  exchange?: string | null;
  sector?: string | null;
  price?: number | null;
  change_pct?: number | null;
  volume?: number | null;
  value?: number | null;
  quant_score: number;
  strength: "Weak" | "Neutral" | "Strong";
  signal: "Watch" | "Actionable" | "Accumulate" | "Wait" | "Avoid" | "Risky" | "Take Profit";
  confidence: number;
  reasons: string[];
  risks: string[];
  last_updated?: string | null;
};

export type TopPicks = {
  picks: TopPick[];
  coverage: string;
  universe_size: number;
  as_of?: string | null;
  disclaimer?: string;
};

const POLL_MS = 60_000;

/**
 * GET /recommendations/top — ranked quant picks over the tracked universe.
 * Research signals only (decision support, not advice). Honest-empty when the
 * quote cache / provider have no data — never mock picks.
 */
export function useTopPicks({
  strategy,
  exchange,
  limit = 10,
}: {
  strategy: "short_aggressive" | "long_conservative";
  exchange?: string | null;
  limit?: number;
}) {
  const api = useApi();
  const params = new URLSearchParams({ limit: String(limit), strategy });
  if (exchange) params.set("exchange", exchange);
  const qs = params.toString();
  const resource = usePollingResource<TopPicks>({
    fetcher: () => api<TopPicks>(`/recommendations/top?${qs}`),
    intervalMs: POLL_MS,
    deps: [qs],
  });
  return {
    data: resource.data,
    loading: resource.loading,
    error: resource.error,
    refresh: resource.refresh,
  };
}
