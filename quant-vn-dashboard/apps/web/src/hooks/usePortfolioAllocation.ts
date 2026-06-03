"use client";

import { useApi } from "@/lib/api";
import type { AllocationSlice } from "@/lib/mock/portfolio";
import { usePollingResource } from "./usePollingResource";

type ApiSlice = { label: string; value: number; weight: number | null };
type AllocationResponse = {
  by_strategy_tag: ApiSlice[];
  by_symbol: ApiSlice[];
  total_market_value: number;
};

const POLL_MS = 60_000;

/**
 * GET /portfolio/allocation — strategy-tag market-value slices.
 *
 * Maps the API ``label`` field to the donut's ``sector`` shape. Returns ``[]``
 * until the backend responds (donut renders an honest empty state); no mock.
 */
export function usePortfolioAllocation() {
  const api = useApi();
  const resource = usePollingResource<AllocationResponse>({
    fetcher: () => api<AllocationResponse>("/portfolio/allocation"),
    intervalMs: POLL_MS,
  });
  const slices: AllocationSlice[] = (resource.data?.by_strategy_tag ?? []).map((s) => ({
    sector: s.label,
    value: s.value,
  }));
  return { data: slices, loading: resource.loading, error: resource.error };
}
