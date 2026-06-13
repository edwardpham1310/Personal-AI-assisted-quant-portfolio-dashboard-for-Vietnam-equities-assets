"use client";

import { useEffect, useRef } from "react";
import { useApi } from "@/lib/api";
import { isoDate, rangeStartDate, type RangeKey } from "@/lib/dateRange";
import { normalizeSeries } from "@/lib/chart";
import { usePollingResource } from "./usePollingResource";

/** One aligned, rebased-to-100 comparison point. */
export type PortfolioVsIndexPoint = { ts: string; portfolio: number; vnindex: number };

type EquityPoint = { ts: string; equity: number };
type IndexBar = { ts: string; close: number };

const POLL_MS = 60_000;

/**
 * Portfolio NAV vs VNINDEX, both rebased to 100 from the first common date.
 *
 * Real data only: portfolio NAV comes from the forward-only equity-curve
 * snapshots (`GET /portfolio/equity-curve`) and VNINDEX from the real daily
 * OHLCV endpoint. The two series are aligned on the dates present in BOTH, so
 * the curve is honest-empty (`[]`) until at least one snapshot overlaps a
 * VNINDEX trading day. No fabricated history; relative-performance rebasing
 * introduces no fee/tax/slippage assumptions and uses only past observations
 * (no lookahead). Caps at the 1-year OHLCV window via the OHLCV range set.
 */
export function usePortfolioVsIndex(range: RangeKey) {
  const api = useApi();
  const ranOnce = useRef(false);

  // Best-effort: seed today's NAV snapshot when the portfolio page mounts, so
  // the forward-only curve grows even without an external cron. Idempotent
  // per trading day; a failure must never break the read.
  useEffect(() => {
    if (ranOnce.current) return;
    ranOnce.current = true;
    void api("/portfolio/snapshots/run", { method: "POST" }).catch(() => {});
  }, [api]);

  const start = rangeStartDate(range);
  const startIso = start ? isoDate(start) : null;
  const endIso = isoDate(new Date());
  const key = `${startIso ?? "ALL"}:${endIso}`;

  const resource = usePollingResource<PortfolioVsIndexPoint[]>({
    fetcher: async () => {
      const eqQs = startIso ? `?start=${startIso}&end=${endIso}` : "";
      // VNINDEX daily history requires start+end; fall back to end..end if ALL.
      const vniQs = `start=${startIso ?? endIso}&end=${endIso}`;
      const [equity, vni] = await Promise.all([
        api<EquityPoint[]>(`/portfolio/equity-curve${eqQs}`),
        api<IndexBar[]>(`/market/ohlcv/daily/VNINDEX?${vniQs}`),
      ]);

      const eqMap = new Map(equity.map((p) => [p.ts.slice(0, 10), p.equity]));
      const vniMap = new Map(vni.map((b) => [b.ts.slice(0, 10), b.close]));
      const common = [...eqMap.keys()].filter((d) => vniMap.has(d)).sort();
      if (common.length === 0) return [];

      const baseEq = eqMap.get(common[0]) ?? 0;
      const baseVni = vniMap.get(common[0]) ?? 0;
      if (!baseEq || !baseVni) return [];

      const points = common.map((ts) => ({
        ts,
        portfolio: ((eqMap.get(ts) ?? baseEq) / baseEq) * 100,
        vnindex: ((vniMap.get(ts) ?? baseVni) / baseVni) * 100,
      }));
      // Defensive ascending sort (common is already sorted; keep the guarantee
      // explicit so the chart always renders oldest→newest, one point per day).
      return normalizeSeries(points, (p) => p.ts);
    },
    intervalMs: POLL_MS,
    deps: [key],
  });

  return {
    data: resource.data ?? [],
    loading: resource.loading,
    error: resource.error,
    lastUpdatedAt: resource.lastUpdatedAt,
    stale: resource.stale,
  };
}
