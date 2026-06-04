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

/**
 * Transport state for the live-quote feed, derived so the UI stays CALM:
 *  - "live"        — SSE connected.
 *  - "polling"     — SSE down but REST fallback is succeeding (healthy path).
 *  - "reconnecting"— SSE down, a poll hasn't resolved yet, but we have data.
 *  - "connecting"  — startup; nothing received yet.
 *  - "offline"     — SSE down AND the REST poll is failing (genuine no-data).
 * These change only on real transport / poll-cadence boundaries, never on every
 * render, so badges don't flicker. Last-known quotes are retained throughout.
 */
export type TransportStatus = "connecting" | "live" | "polling" | "reconnecting" | "offline";

const REST_FALLBACK_INTERVAL_MS = 15_000;
// Stable identity so useEventStream doesn't recreate the EventSource each render.
const QUOTE_EVENT_TYPES = ["quote_update"];

export function useLiveQuotes(symbols: string[]) {
  const api = useApi();
  const [quotes, setQuotes] = useState<LiveQuote[]>([]);
  const [lastUpdate, setLastUpdate] = useState<string | null>(null);
  const [fallbackError, setFallbackError] = useState<string | null>(null);
  const [pollingHealthy, setPollingHealthy] = useState(false);
  const [hasEverReceivedData, setHasEverReceivedData] = useState(false);
  const fallbackTimer = useRef<ReturnType<typeof setInterval> | null>(null);
  const hasEverReceivedDataRef = useRef(false);

  const symbolKey = useMemo(
    () =>
      symbols
        .map((s) => s.trim().toUpperCase())
        .filter(Boolean)
        .sort()
        .join(","),
    [symbols],
  );

  // Apply a fresh batch of quotes (from SSE or REST). Only mark "ever received"
  // when real rows arrive — an empty cold-cache envelope is not "data".
  const applyQuotes = useCallback((rows: LiveQuote[], ts: string) => {
    setQuotes(rows);
    setLastUpdate(ts);
    if (rows.length > 0) {
      hasEverReceivedDataRef.current = true;
      setHasEverReceivedData(true);
    }
  }, []);

  const handleMessage = useCallback(
    (_event: string, payload: QuoteUpdate) => {
      applyQuotes(payload.data, payload.timestamp);
    },
    [applyQuotes],
  );

  const { connected } = useEventStream<QuoteUpdate>({
    path: symbolKey ? `/api/stream/quotes?symbols=${encodeURIComponent(symbolKey)}` : "",
    eventTypes: QUOTE_EVENT_TYPES,
    onMessage: handleMessage,
    enabled: symbolKey.length > 0,
  });

  // REST fallback while the SSE stream is down. Polling SUCCESS is a healthy
  // data path (status "polling"), not an error.
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
        // When SSE is down, keep the visible table stable. Re-applying REST
        // rows every poll makes `stale` and per-row `as of` flicker because the
        // backend recomputes stale status per request. Use polling only to seed
        // a cold panel; live SSE events are the path that refreshes existing
        // visible quotes.
        if (!hasEverReceivedDataRef.current && rows.length > 0) {
          const newestProviderTs = rows.reduce<string | null>((latest, row) => {
            if (!row.ts) return latest;
            if (!latest) return row.ts;
            return new Date(row.ts).getTime() > new Date(latest).getTime() ? row.ts : latest;
          }, null);
          applyQuotes(rows, newestProviderTs ?? new Date().toISOString());
        }
        setPollingHealthy(true);
        setFallbackError(null);
      } catch (err) {
        setPollingHealthy(false);
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
  }, [api, connected, symbolKey, applyQuotes]);

  const transportStatus: TransportStatus = connected
    ? "live"
    : pollingHealthy
      ? "polling"
      : fallbackError
        ? "offline"
        : hasEverReceivedData
          ? "reconnecting"
          : "connecting";

  return {
    quotes,
    lastUpdate,
    transportStatus,
    hasEverReceivedData,
    // Surface a real error only when we are genuinely offline (a failed poll),
    // never the transient "Stream disconnected" noise while polling works.
    error: transportStatus === "offline" ? fallbackError : null,
  };
}
