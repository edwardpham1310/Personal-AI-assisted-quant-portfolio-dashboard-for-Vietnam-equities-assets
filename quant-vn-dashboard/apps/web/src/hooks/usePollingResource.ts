"use client";

import { useCallback, useEffect, useRef, useState } from "react";

/**
 * Generic visibility-aware polling helper.
 *
 * Shared by the portfolio + assets hooks. Pauses while the tab is hidden so
 * we don't churn the backend in background sessions, and re-fetches once when
 * the tab regains focus.
 */
export type PollingResource<T> = {
  data: T | null;
  loading: boolean;
  error: string | null;
  /** ISO timestamp of the last successful fetch, or null if none yet. */
  lastUpdatedAt: string | null;
  /** True when an error is surfaced but we're still showing the last good data. */
  stale: boolean;
  refresh: () => Promise<void>;
};

type Options<T> = {
  fetcher: () => Promise<T>;
  /** Polling interval in ms. Pass ``null`` to disable interval polling. */
  intervalMs?: number | null;
  /** Skip the initial fetch (useful when key deps aren't ready yet). */
  enabled?: boolean;
  /** Re-fetch when any value here changes. */
  deps?: unknown[];
};

export function usePollingResource<T>({
  fetcher,
  intervalMs = 60_000,
  enabled = true,
  deps = [],
}: Options<T>): PollingResource<T> {
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState<boolean>(enabled);
  const [error, setError] = useState<string | null>(null);
  const [lastUpdatedAt, setLastUpdatedAt] = useState<string | null>(null);
  const cancelledRef = useRef(false);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const fetchOnce = useCallback(async () => {
    if (!enabled) return;
    setLoading(true);
    setError(null);
    try {
      const result = await fetcher();
      if (!cancelledRef.current) {
        setData(result);
        setLastUpdatedAt(new Date().toISOString());
      }
    } catch (e) {
      if (!cancelledRef.current) {
        // Keep the last good `data` on screen (no flicker to empty); just
        // surface the error so callers can show a "stale" badge over it.
        setError(e instanceof Error ? e.message : "Request failed");
      }
    } finally {
      if (!cancelledRef.current) setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [enabled, ...deps]);

  useEffect(() => {
    cancelledRef.current = false;
    if (!enabled) {
      setData(null);
      setLoading(false);
      return () => {
        cancelledRef.current = true;
      };
    }

    void fetchOnce();

    const start = () => {
      if (timerRef.current || intervalMs == null) return;
      timerRef.current = setInterval(() => {
        if (cancelledRef.current) return;
        if (typeof document !== "undefined" && document.hidden) return;
        void fetchOnce();
      }, intervalMs);
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
      cancelledRef.current = true;
      stop();
      if (typeof document !== "undefined") {
        document.removeEventListener("visibilitychange", handleVisibility);
      }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [enabled, intervalMs, fetchOnce]);

  return {
    data,
    loading,
    error,
    lastUpdatedAt,
    stale: error != null && data != null,
    refresh: fetchOnce,
  };
}
