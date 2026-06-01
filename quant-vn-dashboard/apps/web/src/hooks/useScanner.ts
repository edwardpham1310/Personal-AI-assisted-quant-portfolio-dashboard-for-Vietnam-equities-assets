"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useApi } from "@/lib/api";

export type SignalCode =
  | "MA20_ABOVE_MA50"
  | "PRICE_ABOVE_MA20"
  | "VOLUME_SPIKE"
  | "BREAKOUT_20D"
  | "BREAKOUT_55D"
  | "RSI_OVERBOUGHT"
  | "RSI_OVERSOLD"
  | "LOW_LIQUIDITY";

export type ScannerTrend = "UPTREND" | "DOWNTREND" | "SIDEWAYS" | "UNKNOWN";

export type ScannerStatus = "BUY_CANDIDATE" | "WATCH" | "HOLD" | "AVOID";

export type ScannerScores = {
  trend: number;
  momentum: number;
  volume: number;
  liquidity: number;
  risk: number;
};

export type ScannerIndicators = {
  ma20: number | null;
  ma50: number | null;
  rsi14: number | null;
  atr14: number | null;
  volume_ratio_20d: number | null;
  high_20d: number | null;
  high_55d: number | null;
  avg_value_20d: number | null;
};

export type ScannerResult = {
  symbol: string;
  last_price: number | null;
  trend: ScannerTrend;
  signals: SignalCode[];
  scores: ScannerScores;
  status: ScannerStatus;
  warnings: string[];
  as_of: string;
  indicators: ScannerIndicators;
};

/** Order used when sorting by status. Lower index = higher priority. */
export const STATUS_ORDER: Record<ScannerStatus, number> = {
  BUY_CANDIDATE: 0,
  WATCH: 1,
  HOLD: 2,
  AVOID: 3,
};

/** Freshness threshold beyond which a scanner row is considered stale. */
export const SCANNER_STALE_MS = 5 * 60 * 1000;

/** Returns true when ``as_of`` is older than the stale threshold. */
export function isScannerRowStale(asOf: string, now: number = Date.now()): boolean {
  const parsed = Date.parse(asOf);
  if (Number.isNaN(parsed)) return true;
  return now - parsed > SCANNER_STALE_MS;
}

const POLL_INTERVAL_MS = 60_000;

type ScannerState<T> = {
  results: T;
  loading: boolean;
  error: string | null;
  refresh: () => Promise<void>;
};

/**
 * Polling fetcher used by both watchlist + universe scanners. Pauses while
 * the document is hidden so we don't churn the backend in background tabs.
 */
function useScannerFetch(path: string | null): ScannerState<ScannerResult[]> {
  const api = useApi();
  const [results, setResults] = useState<ScannerResult[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const fetchOnce = useCallback(async () => {
    if (!path) return;
    setLoading(true);
    setError(null);
    try {
      const data = await api<ScannerResult[]>(path);
      setResults(data);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Scanner request failed");
    } finally {
      setLoading(false);
    }
  }, [api, path]);

  useEffect(() => {
    if (!path) {
      setResults([]);
      return;
    }

    let cancelled = false;
    void fetchOnce();

    const start = () => {
      if (timerRef.current) return;
      timerRef.current = setInterval(() => {
        if (cancelled) return;
        if (typeof document !== "undefined" && document.hidden) return;
        void fetchOnce();
      }, POLL_INTERVAL_MS);
    };

    const stop = () => {
      if (timerRef.current) {
        clearInterval(timerRef.current);
        timerRef.current = null;
      }
    };

    const handleVisibility = () => {
      if (typeof document === "undefined") return;
      if (document.hidden) {
        stop();
      } else {
        void fetchOnce();
        start();
      }
    };

    start();
    if (typeof document !== "undefined") {
      document.addEventListener("visibilitychange", handleVisibility);
    }

    return () => {
      cancelled = true;
      stop();
      if (typeof document !== "undefined") {
        document.removeEventListener("visibilitychange", handleVisibility);
      }
    };
  }, [path, fetchOnce]);

  return { results, loading, error, refresh: fetchOnce };
}

/**
 * Scanner results for a single watchlist. Returns an empty array (no fetch)
 * when ``watchlistId`` is null so callers can leave it unset until the user
 * picks a list.
 */
export function useWatchlistScanner(watchlistId: string | null): ScannerState<ScannerResult[]> {
  return useScannerFetch(watchlistId ? `/scanner/watchlist/${watchlistId}` : null);
}

/** Scanner results across the curated VN30 universe. */
export function useUniverseScanner(): ScannerState<ScannerResult[]> {
  return useScannerFetch("/scanner/universe?vn30=true");
}

/** Single-symbol lookup. Not polled — callers re-mount to refresh. */
export function useSymbolScanner(symbol: string | null): {
  result: ScannerResult | null;
  loading: boolean;
  error: string | null;
  refresh: () => Promise<void>;
} {
  const api = useApi();
  const [result, setResult] = useState<ScannerResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    if (!symbol) return;
    setLoading(true);
    setError(null);
    try {
      const data = await api<ScannerResult>(`/scanner/symbol/${symbol}`);
      setResult(data);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Scanner request failed");
    } finally {
      setLoading(false);
    }
  }, [api, symbol]);

  useEffect(() => {
    if (!symbol) {
      setResult(null);
      return;
    }
    void refresh();
  }, [symbol, refresh]);

  return { result, loading, error, refresh };
}
