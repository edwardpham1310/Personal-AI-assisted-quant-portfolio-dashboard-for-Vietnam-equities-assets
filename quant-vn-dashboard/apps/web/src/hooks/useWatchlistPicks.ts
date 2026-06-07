"use client";

import { useApi } from "@/lib/api";
import { usePollingResource } from "./usePollingResource";
import type { TopPicks } from "./useTopPicks";

const POLL_MS = 60_000;

/**
 * GET /recommendations/watchlist/{id}/picks — quant strength/signal for the
 * symbols in a watchlist, reusing the same scoring as Top Picks. Research
 * signals only (decision support, not advice). Honest-empty when the watchlist
 * is empty or the quote cache is cold — never mock picks. Pass `null` to idle.
 */
export function useWatchlistPicks(
  watchlistId: string | null,
  strategy: "short_aggressive" | "long_conservative" = "short_aggressive",
) {
  const api = useApi();
  const params = new URLSearchParams({ strategy });
  const qs = params.toString();
  const resource = usePollingResource<TopPicks>({
    fetcher: () =>
      api<TopPicks>(`/recommendations/watchlist/${watchlistId}/picks?${qs}`),
    intervalMs: POLL_MS,
    deps: [watchlistId ?? "", qs],
    enabled: watchlistId != null,
  });
  return {
    data: resource.data,
    loading: resource.loading,
    error: resource.error,
    refresh: resource.refresh,
  };
}
