"use client";

import { useCallback, useState } from "react";
import { useEventStream } from "./useEventStream";
import type { LiveQuote } from "./useLiveQuotes";

type QuoteUpdate = {
  type: "quote_update";
  timestamp: string;
  data: LiveQuote[];
};

/**
 * Subscribe to live quotes for an entire watchlist by id. The backend
 * resolves the watchlist symbols server-side under RLS so the user can only
 * stream their own watchlists.
 *
 * No REST fallback here: an empty stream is still useful (the watchlist may
 * literally be empty). Callers that want polling can compose with
 * ``useLiveQuotes`` once they have the symbol list.
 */
export function useWatchlistStream(watchlistId: string | null) {
  const [quotes, setQuotes] = useState<LiveQuote[]>([]);
  const [lastUpdate, setLastUpdate] = useState<string | null>(null);

  const handleMessage = useCallback((_event: string, payload: QuoteUpdate) => {
    setQuotes(payload.data);
    setLastUpdate(payload.timestamp);
  }, []);

  const { connected, error } = useEventStream<QuoteUpdate>({
    path: watchlistId ? `/api/stream/watchlist/${watchlistId}` : "",
    eventTypes: ["quote_update"],
    onMessage: handleMessage,
    enabled: !!watchlistId,
  });

  return { quotes, lastUpdate, connected, error };
}
