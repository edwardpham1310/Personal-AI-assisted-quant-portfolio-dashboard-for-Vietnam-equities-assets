"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useApi } from "@/lib/api";
import { useEventStream } from "./useEventStream";

export type IndexSnapshot = {
  code: string;
  close?: number;
  open?: number;
  high?: number;
  low?: number;
  volume?: number;
  ts?: string;
};

export type MarketOverview = {
  indices: IndexSnapshot[];
  breadth: unknown;
  top_movers: unknown;
};

type Event = {
  type: "market_overview";
  timestamp: string;
  data: MarketOverview;
};

const REST_FALLBACK_INTERVAL_MS = 30_000;
// Stable identity so useEventStream doesn't recreate the EventSource each render.
const OVERVIEW_EVENT_TYPES = ["market_overview"];

export function useMarketOverviewStream() {
  const api = useApi();
  const [overview, setOverview] = useState<MarketOverview | null>(null);
  const [lastUpdate, setLastUpdate] = useState<string | null>(null);
  const [fallbackError, setFallbackError] = useState<string | null>(null);
  const fallbackTimer = useRef<ReturnType<typeof setInterval> | null>(null);

  const handleMessage = useCallback((_event: string, payload: Event) => {
    setOverview(payload.data);
    setLastUpdate(payload.timestamp);
  }, []);

  const { connected, error: streamError } = useEventStream<Event>({
    path: "/api/stream/market-overview",
    eventTypes: OVERVIEW_EVENT_TYPES,
    onMessage: handleMessage,
  });

  useEffect(() => {
    if (connected) {
      if (fallbackTimer.current) {
        clearInterval(fallbackTimer.current);
        fallbackTimer.current = null;
      }
      return;
    }
    const refresh = async () => {
      try {
        const indices = await api<IndexSnapshot[]>("/market/live/indices");
        setOverview({ indices, breadth: null, top_movers: null });
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
  }, [api, connected]);

  return {
    overview,
    lastUpdate,
    connected,
    error: streamError ?? fallbackError,
  };
}
