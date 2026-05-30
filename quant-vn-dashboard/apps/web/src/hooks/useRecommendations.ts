"use client";

import { useCallback, useMemo } from "react";
import { useApi } from "@/lib/api";
import { usePollingResource } from "./usePollingResource";

export type RecommendationProfile = "short_aggressive" | "long_conservative";

export type RecommendationHorizon =
  | "SHORT_T3"
  | "SHORT_1W"
  | "SHORT_2W"
  | "SHORT_1M"
  | "LONG_3M"
  | "LONG_6M"
  | "LONG_12M";

export type RecommendationAction =
  | "BUY_CANDIDATE"
  | "WATCH"
  | "HOLD"
  | "REDUCE"
  | "SELL_CANDIDATE"
  | "AVOID"
  | "REJECTED";

export type RecommendationStatus = "VALID" | "WARNING" | "REJECTED";

export type RecommendationScores = {
  trend: number;
  momentum: number;
  volume: number;
  liquidity: number;
  risk: number;
  risk_inverse: number;
  market_regime: number;
  portfolio_fit: number;
  ml_probability: number | null;
};

export type RecommendationResult = {
  symbol: string;
  profile: RecommendationProfile;
  horizon: RecommendationHorizon;
  action: RecommendationAction;
  status: RecommendationStatus;
  confidence: number;
  final_score: number;
  scores: RecommendationScores;
  last_price: number | null;
  entry_zone_low: number | null;
  entry_zone_high: number | null;
  stop_loss: number | null;
  take_profit_1: number | null;
  take_profit_2: number | null;
  position_size_vnd: number | null;
  estimated_quantity: number | null;
  estimated_total_cost: number | null;
  trend: string;
  signals: string[];
  reasons: string[];
  warnings: string[];
  as_of: string;
  avg_value_20d: number | null;
  disclaimer: string;
};

export const SHORT_HORIZONS: RecommendationHorizon[] = [
  "SHORT_T3",
  "SHORT_1W",
  "SHORT_2W",
  "SHORT_1M",
];

export const LONG_HORIZONS: RecommendationHorizon[] = [
  "LONG_3M",
  "LONG_6M",
  "LONG_12M",
];

export const HORIZON_LABEL: Record<RecommendationHorizon, string> = {
  SHORT_T3: "T+3",
  SHORT_1W: "1 Week",
  SHORT_2W: "2 Weeks",
  SHORT_1M: "1 Month",
  LONG_3M: "3 Months",
  LONG_6M: "6 Months",
  LONG_12M: "12 Months+",
};

export const ACTION_ORDER: Record<RecommendationAction, number> = {
  BUY_CANDIDATE: 0,
  WATCH: 1,
  HOLD: 2,
  REDUCE: 3,
  SELL_CANDIDATE: 4,
  AVOID: 5,
  REJECTED: 6,
};

export function horizonsForProfile(
  profile: RecommendationProfile,
): RecommendationHorizon[] {
  return profile === "short_aggressive" ? SHORT_HORIZONS : LONG_HORIZONS;
}

export function useWatchlistRecommendations(
  watchlistId: string | null,
  profile: RecommendationProfile,
  horizon: RecommendationHorizon,
) {
  const api = useApi();
  const fetcher = useCallback(async () => {
    if (!watchlistId) return [] as RecommendationResult[];
    return api<RecommendationResult[]>(
      `/recommendations/watchlist/${watchlistId}?profile=${profile}&horizon=${horizon}`,
    );
  }, [api, watchlistId, profile, horizon]);

  const { data, loading, error, refresh } = usePollingResource<
    RecommendationResult[]
  >({
    fetcher,
    intervalMs: 60_000,
    enabled: !!watchlistId,
    deps: [watchlistId, profile, horizon],
  });

  return {
    results: data ?? [],
    loading,
    error,
    refresh,
  };
}

export function useSymbolRecommendation(
  symbol: string | null,
  profile: RecommendationProfile,
  horizon: RecommendationHorizon,
) {
  const api = useApi();
  const fetcher = useCallback(async () => {
    if (!symbol) return null as RecommendationResult | null;
    return api<RecommendationResult>(
      `/recommendations/symbol/${symbol}?profile=${profile}&horizon=${horizon}`,
    );
  }, [api, symbol, profile, horizon]);

  const { data, loading, error, refresh } =
    usePollingResource<RecommendationResult | null>({
      fetcher,
      intervalMs: 60_000,
      enabled: !!symbol,
      deps: [symbol, profile, horizon],
    });

  return { result: data, loading, error, refresh };
}

export function useRecommendationPreview() {
  const api = useApi();
  return useMemo(
    () =>
      async (body: {
        symbol: string;
        profile: RecommendationProfile;
        horizon?: RecommendationHorizon;
        total_equity?: number;
      }) =>
        api<RecommendationResult>("/recommendations/preview", {
          method: "POST",
          body: JSON.stringify(body),
        }),
    [api],
  );
}
