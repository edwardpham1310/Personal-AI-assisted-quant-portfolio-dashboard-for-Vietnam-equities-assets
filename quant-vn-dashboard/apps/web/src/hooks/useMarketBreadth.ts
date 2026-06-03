"use client";

import { useApi } from "@/lib/api";
import { MOCK_BREADTH, type MarketBreadth } from "@/lib/mock/market";
import { useAsyncResource } from "./useAsyncResource";

/**
 * Market breadth from ``GET /market/live/breadth`` (poller-populated cache).
 *
 * NOTE: the backend computes breadth over the polled core-symbol universe, not
 * the full market — see ``services/market_breadth.py``. When the cache is cold
 * (poller off) the endpoint returns an all-zero shape; mock only substitutes on
 * a genuine fetch error via ``mockFallback``.
 */
export function useMarketBreadth() {
  const api = useApi();
  return useAsyncResource<MarketBreadth>({
    fetcher: () => api<MarketBreadth>("/market/live/breadth"),
    mockFallback: MOCK_BREADTH,
  });
}
