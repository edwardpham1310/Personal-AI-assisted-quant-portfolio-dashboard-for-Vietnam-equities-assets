"use client";

import { useApi } from "@/lib/api";
import { usePollingResource } from "./usePollingResource";
import type { AssetsPnl } from "./portfolio-types";

const POLL_MS = 60_000;

/**
 * Polls ``GET /assets/pnl`` — realized + unrealized PnL totals plus
 * unrealized contribution per symbol.
 */
export function useAssetsPnl() {
  const api = useApi();
  const resource = usePollingResource<AssetsPnl>({
    fetcher: () => api<AssetsPnl>("/assets/pnl"),
    intervalMs: POLL_MS,
  });
  return {
    pnl: resource.data,
    loading: resource.loading,
    error: resource.error,
    refresh: resource.refresh,
  };
}
