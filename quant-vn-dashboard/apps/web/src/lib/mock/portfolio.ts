/**
 * Deterministic mock data so the dashboard renders before the portfolio
 * pipeline lands. The "Mock Data" badge surfaces this in the UI.
 */

export type PortfolioSummary = {
  total_equity_vnd: number;
  net_pnl_vnd: number;
  net_pnl_pct: number;
  today_pnl_vnd: number;
  available_cash_vnd: number;
  pending_cash_vnd: number;
  risk_score: number; // 0..1
  market_regime: string;
};

export const MOCK_PORTFOLIO_SUMMARY: PortfolioSummary = {
  total_equity_vnd: 1_250_000_000,
  net_pnl_vnd: 75_000_000,
  net_pnl_pct: 0.063,
  today_pnl_vnd: 12_500_000,
  available_cash_vnd: 220_000_000,
  pending_cash_vnd: 45_000_000,
  risk_score: 0.42,
  market_regime: "Cautiously Bullish",
};

export type EquityPoint = { ts: string; equity: number };

export const MOCK_EQUITY_CURVE: EquityPoint[] = Array.from({ length: 90 }, (_, i) => {
  const day = new Date(Date.now() - (89 - i) * 86_400_000);
  const equity =
    1_000_000_000 + i * 2_500_000 + Math.sin(i / 7) * 15_000_000 + Math.cos(i / 13) * 7_000_000;
  return { ts: day.toISOString().slice(0, 10), equity: Math.round(equity) };
});

export type AllocationSlice = { sector: string; value: number };

export const MOCK_ALLOCATION: AllocationSlice[] = [
  { sector: "Banking", value: 380_000_000 },
  { sector: "Technology", value: 290_000_000 },
  { sector: "Consumer", value: 210_000_000 },
  { sector: "Industrial", value: 150_000_000 },
  { sector: "Cash", value: 220_000_000 },
];

export type PnlBucket = { bucket: string; value: number };

export const MOCK_PNL_BUCKETS: PnlBucket[] = [
  { bucket: "Banking", value: 28_000_000 },
  { bucket: "Technology", value: 42_000_000 },
  { bucket: "Consumer", value: 9_000_000 },
  { bucket: "Industrial", value: -16_000_000 },
  { bucket: "Fees", value: -3_000_000 },
];

export type Candidate = {
  symbol: string;
  score: number;
  reason: string;
};

export const MOCK_BUY_CANDIDATES: Candidate[] = [
  { symbol: "FPT", score: 0.81, reason: "Breakout > 20D high with rising RSI" },
  { symbol: "MWG", score: 0.74, reason: "Pullback to MA50 with volume support" },
  { symbol: "VCB", score: 0.69, reason: "VN30 trend leader, momentum positive" },
];

export const MOCK_SELL_CANDIDATES: Candidate[] = [
  { symbol: "HPG", score: 0.71, reason: "Trend exhaustion + ATR expansion" },
  { symbol: "STB", score: 0.58, reason: "Below MA50, fading volume" },
];

export type RiskAlert = { severity: "info" | "warning" | "error"; message: string };

export const MOCK_RISK_ALERTS: RiskAlert[] = [
  { severity: "warning", message: "Banking concentration above 30% of equity" },
  { severity: "info", message: "VNINDEX 30D realized vol above 12-month median" },
];

export type SettlementAlert = { ts: string; message: string };

export const MOCK_SETTLEMENT_ALERTS: SettlementAlert[] = [
  { ts: "2026-05-30", message: "Pending FPT sale proceeds settle 2026-05-30 (T+2)" },
];

export type DataQualityStatus = {
  status: "OK" | "WARN" | "ERROR";
  ingest_lag_minutes: number;
  issues_24h: number;
  note: string;
};

export const MOCK_DATA_QUALITY: DataQualityStatus = {
  status: "OK",
  ingest_lag_minutes: 4,
  issues_24h: 0,
  note: "Daily OHLCV ingest current. No SSI / DuckDB anomalies in last 24h.",
};
