"use client";

import { useApi } from "@/lib/api";
import type { PnlBucket } from "@/lib/mock/portfolio";
import { usePollingResource } from "./usePollingResource";

type WaterfallResponse = {
  buckets: PnlBucket[];
  as_of: string | null;
};

const POLL_MS = 60_000;

/**
 * GET /assets/pnl/waterfall — ordered Realized → Unrealized → Costs → Net
 * contribution bars. Returns ``[]`` until the backend responds (the chart
 * renders an honest empty state); no mock fallback.
 */
export function usePnlWaterfall() {
  const api = useApi();
  const resource = usePollingResource<WaterfallResponse>({
    fetcher: () => api<WaterfallResponse>("/assets/pnl/waterfall"),
    intervalMs: POLL_MS,
  });
  const buckets: PnlBucket[] = resource.data?.buckets ?? [];
  return {
    data: buckets,
    asOf: resource.data?.as_of ?? resource.lastUpdatedAt,
    loading: resource.loading,
    error: resource.error,
    stale: resource.stale,
    refresh: resource.refresh,
  };
}
