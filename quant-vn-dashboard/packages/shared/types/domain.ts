import type { VnExchange } from "../constants/markets";

export type Symbol = string;

export type Quote = {
  symbol: Symbol;
  exchange?: VnExchange;
  price: number;
  bid?: number;
  ask?: number;
  volume?: number;
  /** ISO 8601 timestamp (UTC). */
  ts: string;
  /** True when the quote is older than the freshness threshold. */
  stale: boolean;
};

export type Holding = {
  symbol: Symbol;
  settled_qty: number;
  pending_qty: number;
  avg_cost_vnd: number;
};

export type RecommendationAction = "BUY" | "SELL" | "HOLD" | "REDUCE";

export type Recommendation = {
  id: string;
  symbol: Symbol;
  action: RecommendationAction;
  score: number | null;
  confidence: number | null;
  reasons: string[];
  risks: string[];
  data_timestamp: string;
};
