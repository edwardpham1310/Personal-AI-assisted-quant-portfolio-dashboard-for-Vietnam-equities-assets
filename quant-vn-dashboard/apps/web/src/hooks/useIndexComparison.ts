"use client";

import { useApi } from "@/lib/api";
import { makeMockIndexComparison } from "@/lib/mock/market";
import { useAsyncResource } from "./useAsyncResource";

type ApiBar = { ts: string; close: number };

export type IndexComparisonPoint = { ts: string; vnindex: number; vn30: number };

function isoDate(d: Date): string {
  return d.toISOString().slice(0, 10);
}

/**
 * VNINDEX vs VN30, rebased to 100, over a selectable lookback window.
 *
 * Both series come from the real ``GET /market/ohlcv/daily/{symbol}?start=&end=``
 * endpoint. They are aligned on the dates present in BOTH series and rebased
 * from the first common date so both lines start at exactly 100. Empty result
 * (no overlapping bars) renders an honest empty state; mock only appears in dev
 * on a fetch error (``mockFallback``), never in production.
 *
 * ``days`` must stay within the backend daily cap (365).
 */
export function useIndexComparison(days = 90) {
  const api = useApi();
  const lookback = Math.min(365, Math.max(1, days));
  return useAsyncResource<IndexComparisonPoint[]>({
    fetcher: async () => {
      const end = new Date();
      const start = new Date(Date.now() - (lookback - 1) * 86_400_000);
      const qs = `start=${isoDate(start)}&end=${isoDate(end)}`;
      const [vni, vn30] = await Promise.all([
        api<ApiBar[]>(`/market/ohlcv/daily/VNINDEX?${qs}`),
        api<ApiBar[]>(`/market/ohlcv/daily/VN30?${qs}`),
      ]);
      const vniMap = new Map(vni.map((r) => [r.ts.slice(0, 10), r.close]));
      const vn30Map = new Map(vn30.map((r) => [r.ts.slice(0, 10), r.close]));
      const common = [...vniMap.keys()].filter((ts) => vn30Map.has(ts)).sort();
      if (common.length === 0) return [];
      const baseV = vniMap.get(common[0]) ?? 0;
      const base30 = vn30Map.get(common[0]) ?? 0;
      if (!baseV || !base30) return [];
      return common.map((ts) => ({
        ts,
        vnindex: ((vniMap.get(ts) ?? baseV) / baseV) * 100,
        vn30: ((vn30Map.get(ts) ?? base30) / base30) * 100,
      }));
    },
    mockFallback: makeMockIndexComparison(lookback),
    deps: [lookback],
  });
}
