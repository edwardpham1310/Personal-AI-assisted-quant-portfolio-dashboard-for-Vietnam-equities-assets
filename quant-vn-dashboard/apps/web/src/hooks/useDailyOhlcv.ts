"use client";

import { useApi } from "@/lib/api";
import { sortByTimeAsc } from "@/lib/dateRange";
import { makeMockOhlcv, type OHLCV } from "@/lib/mock/market";
import { useAsyncResource } from "./useAsyncResource";

type ApiBar = {
  symbol: string;
  ts: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
};

function isoDate(d: Date): string {
  return d.toISOString().slice(0, 10);
}

export function useDailyOhlcv(symbol: string, days = 180) {
  const api = useApi();
  const upper = symbol.toUpperCase();
  // Daily history endpoint caps at 365 days; clamp so a large range never 400s.
  const lookback = Math.min(365, Math.max(1, days));
  return useAsyncResource<OHLCV[]>({
    fetcher: async () => {
      const end = new Date();
      const start = new Date(Date.now() - (lookback - 1) * 86_400_000);
      const rows = await api<ApiBar[]>(
        `/market/ohlcv/daily/${encodeURIComponent(upper)}?start=${isoDate(start)}&end=${isoDate(end)}`,
      );
      const mapped = rows.map((r) => ({
        ts: r.ts.slice(0, 10),
        open: r.open,
        high: r.high,
        low: r.low,
        close: r.close,
        volume: r.volume,
      }));
      // Defensive: rolling-MA enrichment + candlestick rendering require strict
      // oldest→newest order even if a provider returns bars out of order.
      return sortByTimeAsc(mapped, (r) => r.ts);
    },
    mockFallback: makeMockOhlcv(upper, lookback),
    deps: [upper, lookback],
  });
}
