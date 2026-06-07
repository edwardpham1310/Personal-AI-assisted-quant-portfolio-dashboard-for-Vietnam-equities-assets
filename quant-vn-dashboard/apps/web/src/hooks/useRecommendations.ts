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

export type DataStatus = "FRESH" | "STALE" | "DATA_UNAVAILABLE" | "PROVIDER_ERROR";

export type ChartContext = {
  timeframe: string;
  last_candle_time: string | null;
  trend: string;
  ma20: number | null;
  ma50: number | null;
  rsi: number | null;
  volume_ratio_20d: number | null;
  atr14: number | null;
};

export type LatestQuotePayload = {
  symbol: string;
  price: number;
  reference_price?: number | null;
  change?: number | null;
  change_pct?: number | null;
  volume?: number | null;
  ceiling_price?: number | null;
  floor_price?: number | null;
  value?: number | null;
  ts: string;
  stale: boolean;
  source: string;
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
  // Phase 2 chart-context fields.
  data_status: DataStatus;
  latest_quote: LatestQuotePayload | null;
  chart_context: ChartContext | null;
  chart_url: string;
  disclaimer: string;
  // Feature 7 portfolio-aware fields (held_weight_pct is weight within holdings).
  is_held: boolean;
  held_weight_pct: number | null;
  held_quantity: number | null;
  held_avg_cost: number | null;
  held_unrealized_pct: number | null;
  portfolio_note: string | null;
};

export const SHORT_HORIZONS: RecommendationHorizon[] = [
  "SHORT_T3",
  "SHORT_1W",
  "SHORT_2W",
  "SHORT_1M",
];

export const LONG_HORIZONS: RecommendationHorizon[] = ["LONG_3M", "LONG_6M", "LONG_12M"];

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

export function horizonsForProfile(profile: RecommendationProfile): RecommendationHorizon[] {
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

  const { data, loading, error, refresh } = usePollingResource<RecommendationResult[]>({
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

  const { data, loading, error, refresh } = usePollingResource<RecommendationResult | null>({
    fetcher,
    intervalMs: 60_000,
    enabled: !!symbol,
    deps: [symbol, profile, horizon],
  });

  return { result: data, loading, error, refresh };
}

export type RecommendationStrength = "Weak" | "Neutral" | "Strong";
export type RecommendationSignal =
  | "Watch"
  | "Actionable"
  | "Accumulate"
  | "Wait"
  | "Avoid"
  | "Risky"
  | "Take Profit";

export type ScoreContribution = {
  component: string;
  label: string;
  score: number | null;
  weight: number;
  contribution: number;
};

export type RecommendationExplanation = {
  symbol: string;
  profile: RecommendationProfile;
  horizon: RecommendationHorizon;
  action: RecommendationAction;
  strength: RecommendationStrength;
  signal: RecommendationSignal;
  final_score: number;
  confidence: number;
  action_threshold_used: number;
  contributions: ScoreContribution[];
  summary: string;
  reasons: string[];
  risks: string[];
  data_status: DataStatus;
  as_of: string;
  disclaimer: string;
};

/**
 * GET /recommendations/explain/{symbol} — weighted contribution breakdown for
 * one symbol. Read-only "why" view (no snapshot written). Pass null to idle.
 */
export function useRecommendationExplanation(
  symbol: string | null,
  profile: RecommendationProfile,
  horizon: RecommendationHorizon,
) {
  const api = useApi();
  const fetcher = useCallback(async () => {
    if (!symbol) return null as RecommendationExplanation | null;
    return api<RecommendationExplanation>(
      `/recommendations/explain/${symbol}?profile=${profile}&horizon=${horizon}`,
    );
  }, [api, symbol, profile, horizon]);

  const { data, loading, error, refresh } =
    usePollingResource<RecommendationExplanation | null>({
      fetcher,
      intervalMs: 60_000,
      enabled: !!symbol,
      deps: [symbol, profile, horizon],
    });

  return { explanation: data, loading, error, refresh };
}

export type RecommendationHistoryItem = {
  id: string | null;
  symbol: string;
  profile: string | null;
  horizon: string;
  action: string;
  signal: RecommendationSignal;
  strength: RecommendationStrength;
  final_score: number;
  confidence: number | null;
  status: string;
  reference_price: number | null;
  reasons: string[];
  warnings: string[];
  created_at: string | null;
  as_of: string | null;
};

export type RecommendationHistory = {
  items: RecommendationHistoryItem[];
  count: number;
  range: string;
  as_of: string | null;
  disclaimer: string;
};

export type RecommendationPerformanceItem = {
  id: string | null;
  symbol: string;
  horizon: string;
  action: string;
  signal: RecommendationSignal;
  reference_price: number;
  current_price: number;
  return_pct: number;
  stale: boolean;
  created_at: string | null;
  priced_as_of: string | null;
};

export type RecommendationPerformance = {
  items: RecommendationPerformanceItem[];
  total: number;
  evaluated: number;
  skipped_no_reference: number;
  skipped_no_quote: number;
  win_rate: number | null;
  avg_return_pct: number | null;
  best: RecommendationPerformanceItem | null;
  worst: RecommendationPerformanceItem | null;
  range: string;
  as_of: string | null;
  basis: string;
  disclaimer: string;
};

/** GET /recommendations/history — past snapshots, ascending by date. */
export function useRecommendationHistory(range: string, symbol?: string | null) {
  const api = useApi();
  const params = new URLSearchParams({ range });
  if (symbol) params.set("symbol", symbol);
  const qs = params.toString();
  const { data, loading, error, refresh } = usePollingResource<RecommendationHistory>({
    fetcher: () => api<RecommendationHistory>(`/recommendations/history?${qs}`),
    intervalMs: 60_000,
    deps: [qs],
  });
  return { data, loading, error, refresh };
}

/** GET /recommendations/performance — hypothetical mark-to-market (not trades). */
export function useRecommendationPerformance(range: string, symbol?: string | null) {
  const api = useApi();
  const params = new URLSearchParams({ range });
  if (symbol) params.set("symbol", symbol);
  const qs = params.toString();
  const { data, loading, error, refresh } = usePollingResource<RecommendationPerformance>({
    fetcher: () => api<RecommendationPerformance>(`/recommendations/performance?${qs}`),
    intervalMs: 60_000,
    deps: [qs],
  });
  return { data, loading, error, refresh };
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
