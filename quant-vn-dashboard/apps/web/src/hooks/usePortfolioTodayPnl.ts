"use client";

import { useApi } from "@/lib/api";
import { usePollingResource } from "./usePollingResource";

/** GET /portfolio/today-pnl — intraday mark-to-market vs session reference. */
export type TodayPnl = {
  total_day_pnl: number;
  as_of: string | null;
  warnings: string[];
};

const POLL_MS = 30_000;

export function usePortfolioTodayPnl() {
  const api = useApi();
  const resource = usePollingResource<TodayPnl>({
    fetcher: () => api<TodayPnl>("/portfolio/today-pnl"),
    intervalMs: POLL_MS,
  });
  return { data: resource.data, loading: resource.loading, error: resource.error };
}
