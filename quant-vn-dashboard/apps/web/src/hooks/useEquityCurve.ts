"use client";

import { useEffect, useRef } from "react";
import { useApi } from "@/lib/api";
import { isoDate, rangeStartDate, sortByTimeAsc, type RangeKey } from "@/lib/dateRange";
import type { EquityPoint } from "@/lib/mock/portfolio";
import { usePollingResource } from "./usePollingResource";

const POLL_MS = 60_000;

/**
 * GET /portfolio/equity-curve — daily NAV history for the default account,
 * scoped to a calendar range. Forward-only: returns ``[]`` until at least one
 * in-range snapshot exists (the chart renders an honest "No portfolio history
 * yet" empty state).
 *
 * `range` selects an inclusive calendar window (e.g. `YTD`, `1Y`, `ALL`) — we
 * derive `start`/`end` and pass them to the backend, which filters by
 * `snapshot_date`. On mount we fire ``POST /portfolio/snapshots/run`` once
 * (best-effort) so opening the dashboard records today's point even without an
 * external cron; the writer is idempotent per trading day.
 */
export function useEquityCurve(range: RangeKey = "3M") {
  const api = useApi();
  const ranOnce = useRef(false);

  useEffect(() => {
    if (ranOnce.current) return;
    ranOnce.current = true;
    // Best-effort: a failed snapshot must never break the read.
    void api("/portfolio/snapshots/run", { method: "POST" }).catch(() => {});
  }, [api]);

  const start = rangeStartDate(range);
  const qs = start ? `?start=${isoDate(start)}&end=${isoDate(new Date())}` : "";

  const resource = usePollingResource<EquityPoint[]>({
    fetcher: async () => {
      const rows = await api<EquityPoint[]>(`/portfolio/equity-curve${qs}`);
      // Backend already returns ascending; sort defensively in case the source changes.
      return sortByTimeAsc(rows, (r) => r.ts);
    },
    intervalMs: POLL_MS,
    deps: [qs],
  });
  return {
    data: resource.data ?? [],
    loading: resource.loading,
    error: resource.error,
    refresh: resource.refresh,
  };
}
