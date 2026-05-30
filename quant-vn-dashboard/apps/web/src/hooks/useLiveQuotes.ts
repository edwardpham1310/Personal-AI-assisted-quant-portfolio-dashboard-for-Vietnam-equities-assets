"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useApi } from "@/lib/api";
import { useEventStream } from "./useEventStream";

export type LiveQuote = {
  symbol: string;
  exchange?: string | null;
  price: number;
  reference_price?: number | null;
  change?: number | null;
  change_pct?: number | null;
  volume?: number | null;
  ts: string;
  stale: boolean;
  source: string;
};

type QuoteUpdate = {
  type: "quote_update";
  timestamp: string;
  data: LiveQuote[];
};

const REST_FALLBACK_INTERVAL_MS = 15_000;

/**
 * Subscribe to live quote updates for the given symbols.
 *
 * Tries SSE first via ``/api/stream/quotes``. When the connection drops,
 * falls back to polling ``/market/live/quotes`` every 15s so the dashboard
 * stays useful even on flaky networks.
 */
export function useLiveQuotes(symbols: string[]) {
  const api = useApi();
  const [quotes, setQuotes] = useState<LiveQuote[]>([]);
  const [lastUpdate, setLastUpdate] = useState<string | null>(null);
  const [fallbackError, setFallbackError] = useState<string | null>(null);
  const fallbackTimer = useRef<ReturnType<typeof setInterval> | null>(null);

  const symbolKey = useMemo(
    () =>
      symbols
        .map((s) => s.trim().toUpperCase())
        .filter(Boolean)
        .sort()
        .join(","),
    [symbols],
  );

  const handleMessage = useCallback(
    (_event: string, payload: QuoteUpdate) => {
      setQuotes(payload.data);
      setLastUpdate(payload.timestamp);
    },
    [],
  );

  const { connected, error: streamError } = useEventStream<QuoteUpdate>({
    path: symbolKey
      ? `/api/stream/quotes?symbols=${encodeURIComponent(symbolKey)}`
      : "",
    eventTypes: ["quote_update"],
    onMessage: handleMessage,
    enabled: symbolKey.length > 0,
  });

  // REST fallback when the stream is down.
  useEffect(() => {
    if (!symbolKey || connected) {
      if (fallbackTimer.current) {
        clearInterval(fallbackTimer.current);
        fallbackTimer.current = null;
      }
      return;
    }

    const refresh = async () => {
      try {
        const rows = await api<LiveQuote[]>(
          `/market/live/quotes?symbols=${encodeURIComponent(symbolKey)}`,
        );
        setQuotes(rows);
        setLastUpdate(new Date().toISOString());
        setFallbackError(null);
      } catch (err) {
        setFallbackError(err instanceof Error ? err.message : "Polling failed");
      }
    };

    void refresh();
    fallbackTimer.current = setInterval(refresh, REST_FALLBACK_INTERVAL_MS);
    return () => {
      if (fallbackTimer.current) {
        clearInterval(fallbackTimer.current);
        fallbackTimer.current = null;
      }
    };
  }, [api, connected, symbolKey]);

  return {
    quotes,
    lastUpdate,
    connected,
    error: streamError ?? fallbackError,
  };
}
