"use client";

import { isProductionBuild } from "@/lib/env";
import { MOCK_BUY_CANDIDATES, MOCK_SELL_CANDIDATES, type Candidate } from "@/lib/mock/portfolio";
import { useAsyncResource } from "./useAsyncResource";

export type Candidates = { buy: Candidate[]; sell: Candidate[] };

const EMPTY: Candidates = { buy: [], sell: [] };

/**
 * Buy/sell candidates for the Dashboard Home action panels.
 *
 * The recommendations endpoint for this surface is not wired yet. In
 * PRODUCTION we resolve to an EMPTY result so the panels render an honest
 * "No candidates today." empty state — we must never show synthetic
 * candidates to a real user. In development we keep the mock (``alwaysMock``)
 * so the UI can be built and visualised, surfaced with a "Mock" badge.
 *
 * TODO: point ``fetcher`` at the real candidates endpoint once it exists.
 */
export function useRecommendationCandidates() {
  return useAsyncResource<Candidates>({
    fetcher: () => Promise.resolve(EMPTY),
    mockFallback: { buy: MOCK_BUY_CANDIDATES, sell: MOCK_SELL_CANDIDATES },
    alwaysMock: !isProductionBuild,
  });
}
