import type { VnExchange } from "@quant-shared/constants/markets";

/**
 * Shared TypeScript shapes used by the Portfolio and Assets & PnL pages.
 *
 * These mirror the FastAPI response models on the backend. Keep them in
 * sync with `quant-vn-dashboard/apps/api/.../portfolio/*` and `.../assets/*`.
 *
 * IMPORTANT: every numeric field is in VND. ``percent`` fields are returned
 * as fractions (0.05 = 5%) only when the brief explicitly says so — the
 * positions/summary endpoints already return percents in *percent units*
 * (e.g. -3.42 for -3.42%). The hooks pass them through unchanged.
 */
export type EnrichedPosition = {
  id: string;
  account_id: string;
  symbol: string;
  exchange: VnExchange;
  quantity: number;
  sellable_quantity: number;
  pending_quantity: number;
  avg_cost: number;
  market_price: number | null;
  market_value: number | null;
  unrealized_pnl: number | null;
  unrealized_pnl_pct: number | null;
  weight: number | null;
  strategy_tag: string | null;
  note: string | null;
  warnings: string[];
  last_marked_at: string | null;
};

export type StrategyTagBucket = {
  cost: number;
  market_value: number;
  unrealized_pnl: number;
  weight: number;
};

export type PortfolioSummary = {
  position_count: number;
  total_cost: number;
  total_market_value: number;
  total_unrealized_pnl: number;
  total_unrealized_pnl_pct: number | null;
  by_strategy_tag: Record<string, StrategyTagBucket>;
  last_marked_at: string | null;
  warnings: string[];
};

export type AssetsSummary = {
  settled_cash: number;
  pending_cash: number;
  advanced_cash: number;
  cash_advance_liability: number;
  stock_market_value: number;
  total_equity: number;
  available_buying_power: number;
  withdrawable_cash: number;
  currency: "VND";
  as_of: string | null;
};

export type PnlSymbolEntry = { symbol: string; value: number };

export type AssetsPnl = {
  realized: number;
  unrealized: number;
  total: number;
  by_symbol: PnlSymbolEntry[];
};

export type CostPeriod = "MTD" | "YTD" | "ALL";

export type CostBreakdown = {
  brokerage_fee: number;
  vat: number;
  sell_tax: number;
  cash_advance_fee: number;
  slippage_estimate: number;
  total: number;
  period: CostPeriod;
};

export type PositionCreate = {
  symbol: string;
  exchange: VnExchange;
  quantity: number;
  avg_cost: number;
  strategy_tag?: string | null;
  note?: string | null;
};

export type PositionUpdate = Partial<PositionCreate>;
