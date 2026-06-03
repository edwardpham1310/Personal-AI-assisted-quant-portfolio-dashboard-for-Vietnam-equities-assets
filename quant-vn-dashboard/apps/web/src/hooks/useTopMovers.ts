"use client";

import { useApi } from "@/lib/api";
import { MOCK_TOP_MOVERS, type TopMovers } from "@/lib/mock/market";
import { useAsyncResource } from "./useAsyncResource";

/**
 * Top movers from ``GET /market/live/top-movers`` (poller-populated cache).
 *
 * Computed over the polled core-symbol universe. ``by_volume_spike`` is always
 * empty until an ADV baseline is wired (see ``services/market_breadth.py``).
 * Missing keys are defaulted to ``[]`` so ``TopMoversCard`` can't crash on a
 * partial payload; mock only substitutes on a genuine fetch error.
 */
export function useTopMovers() {
  const api = useApi();
  return useAsyncResource<TopMovers>({
    fetcher: async () => {
      const r = await api<Partial<TopMovers>>("/market/live/top-movers");
      return {
        gainers: r.gainers ?? [],
        losers: r.losers ?? [],
        by_value: r.by_value ?? [],
        by_volume_spike: r.by_volume_spike ?? [],
      };
    },
    mockFallback: MOCK_TOP_MOVERS,
  });
}
