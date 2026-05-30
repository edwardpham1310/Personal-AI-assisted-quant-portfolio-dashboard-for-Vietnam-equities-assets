"use client";

import { useApi } from "@/lib/api";
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
  return useAsyncResource<OHLCV[]>({
    fetcher: async () => {
      const end = new Date();
      const start = new Date(Date.now() - (days - 1) * 86_400_000);
      const rows = await api<ApiBar[]>(
        `/market/ohlcv/daily/${encodeURIComponent(upper)}?start=${isoDate(start)}&end=${isoDate(end)}`,
      );
      return rows.map((r) => ({
        ts: r.ts.slice(0, 10),
        open: r.open,
        high: r.high,
        low: r.low,
        close: r.close,
        volume: r.volume,
      }));
    },
    mockFallback: makeMockOhlcv(upper, days),
    deps: [upper, days],
  });
}
