"use client";

import { MOCK_TOP_MOVERS, type TopMovers } from "@/lib/mock/market";
import { useAsyncResource } from "./useAsyncResource";

/**
 * Top movers are derived in the backend full-market scan, which is still
 * pending wiring. Mock mode for now.
 */
export function useTopMovers() {
  return useAsyncResource<TopMovers>({
    fetcher: () => Promise.reject(new Error("top_movers_endpoint_pending")),
    mockFallback: MOCK_TOP_MOVERS,
    alwaysMock: true,
  });
}
