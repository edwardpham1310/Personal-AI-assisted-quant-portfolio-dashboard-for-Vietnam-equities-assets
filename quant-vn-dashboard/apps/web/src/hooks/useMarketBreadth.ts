"use client";

import { MOCK_BREADTH, type MarketBreadth } from "@/lib/mock/market";
import { useAsyncResource } from "./useAsyncResource";

/**
 * Market breadth is computed by a backend job that has not been wired yet
 * (see ``market:breadth`` cache key in ``services/market_cache.py``). Until
 * then this hook stays on the mock fallback so the UI is exercised.
 */
export function useMarketBreadth() {
  return useAsyncResource<MarketBreadth>({
    fetcher: () => Promise.reject(new Error("breadth_endpoint_pending")),
    mockFallback: MOCK_BREADTH,
    alwaysMock: true,
  });
}
