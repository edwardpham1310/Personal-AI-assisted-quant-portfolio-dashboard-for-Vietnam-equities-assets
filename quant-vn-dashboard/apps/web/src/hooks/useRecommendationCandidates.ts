"use client";

import { MOCK_BUY_CANDIDATES, MOCK_SELL_CANDIDATES, type Candidate } from "@/lib/mock/portfolio";
import { useAsyncResource } from "./useAsyncResource";

export type Candidates = { buy: Candidate[]; sell: Candidate[] };

export function useRecommendationCandidates() {
  return useAsyncResource<Candidates>({
    fetcher: () => Promise.reject(new Error("recommendations_endpoint_pending")),
    mockFallback: { buy: MOCK_BUY_CANDIDATES, sell: MOCK_SELL_CANDIDATES },
    alwaysMock: true,
  });
}
