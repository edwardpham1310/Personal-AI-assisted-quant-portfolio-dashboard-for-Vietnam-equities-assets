"use client";

import { useApi } from "@/lib/api";
import { isProductionBuild } from "@/lib/env";
import { MOCK_BUY_CANDIDATES, MOCK_SELL_CANDIDATES, type Candidate } from "@/lib/mock/portfolio";
import type { TopPicks } from "./useTopPicks";
import { useAsyncResource } from "./useAsyncResource";

export type Candidates = { buy: Candidate[]; sell: Candidate[] };

const BUY_SIGNALS = new Set(["Actionable", "Accumulate"]);
const SELL_SIGNALS = new Set(["Avoid", "Risky", "Take Profit"]);
const MAX_PER_PANEL = 5;

/**
 * Buy/sell candidates for the Dashboard Home action panels, sourced from the
 * real recommendation engine (`GET /recommendations/top`). Buy = Actionable /
 * Accumulate signals; Sell/Reduce = Avoid / Risky / Take Profit. Honest-empty
 * when the engine returns nothing. Dev shows mock (badged); prod is real only.
 */
export function useRecommendationCandidates() {
  const api = useApi();
  return useAsyncResource<Candidates>({
    fetcher: async () => {
      const data = await api<TopPicks>(
        "/recommendations/top?strategy=short_aggressive&limit=20",
      );
      const buy: Candidate[] = [];
      const sell: Candidate[] = [];
      for (const p of data.picks ?? []) {
        const c: Candidate = {
          symbol: p.symbol,
          score: p.quant_score / 100,
          reason: p.reasons?.[0] ?? p.signal,
        };
        if (BUY_SIGNALS.has(p.signal) && buy.length < MAX_PER_PANEL) buy.push(c);
        else if (SELL_SIGNALS.has(p.signal) && sell.length < MAX_PER_PANEL) sell.push(c);
      }
      return { buy, sell };
    },
    mockFallback: { buy: MOCK_BUY_CANDIDATES, sell: MOCK_SELL_CANDIDATES },
    alwaysMock: !isProductionBuild,
  });
}
