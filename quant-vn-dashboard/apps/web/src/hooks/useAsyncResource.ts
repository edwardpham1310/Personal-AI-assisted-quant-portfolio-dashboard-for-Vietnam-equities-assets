"use client";

import { useEffect, useState } from "react";

import { isProductionBuild } from "@/lib/env";

export type AsyncState<T> = {
  data: T;
  isLoading: boolean;
  error: string | null;
  /** True when ``data`` comes from the mock fallback rather than the live API. */
  isMock: boolean;
  /** ISO timestamp of the last successful live fetch, or null if none yet. */
  lastUpdatedAt: string | null;
  /** True when an error is surfaced but we're still showing the last good (real) data. */
  stale: boolean;
  /** True once at least one real fetch has succeeded (data is real, not the seed mock). */
  hasLoadedReal: boolean;
  refetch: () => void;
};

type Options<T> = {
  fetcher: () => Promise<T>;
  /** Returned synchronously while the fetch is in-flight or when it fails. */
  mockFallback: T;
  /** When true, skip the fetch entirely and stay on mock data. */
  alwaysMock?: boolean;
  /** Dependency list — bumping any value triggers a refetch. */
  deps?: unknown[];
  /** Phase 2A: when true and the fetch fails, the hook leaves ``data`` at
   *  the initial mockFallback (so the UI doesn't crash) but flips ``isMock``
   *  to true AND surfaces ``error`` so callers can render an error banner
   *  instead of silently displaying fake data. Defaults to true on
   *  production builds (``NEXT_PUBLIC_APP_ENV=production``). Set to false
   *  explicitly only for dev-only fixture hooks whose fallback is
   *  intentionally synthetic. */
  disableMockOnError?: boolean;
};

/**
 * Tiny SWR-style hook. Exposes the same shape for every dashboard data
 * source: a value the UI can render immediately, a loading flag, an
 * error string, an ``isMock`` indicator, and a manual refetch.
 */
export function useAsyncResource<T>({
  fetcher,
  mockFallback,
  alwaysMock = false,
  deps = [],
  disableMockOnError = isProductionBuild,
}: Options<T>): AsyncState<T> {
  const [data, setData] = useState<T>(mockFallback);
  const [isLoading, setIsLoading] = useState<boolean>(!alwaysMock);
  const [error, setError] = useState<string | null>(null);
  const [isMock, setIsMock] = useState<boolean>(alwaysMock);
  const [lastUpdatedAt, setLastUpdatedAt] = useState<string | null>(null);
  const [hasLoadedReal, setHasLoadedReal] = useState<boolean>(false);
  const [reload, setReload] = useState<number>(0);

  useEffect(() => {
    if (alwaysMock) {
      setData(mockFallback);
      setIsLoading(false);
      setIsMock(true);
      setError(null);
      return;
    }
    let cancelled = false;
    setIsLoading(true);
    setError(null);
    fetcher()
      .then((next) => {
        if (cancelled) return;
        setData(next);
        setIsMock(false);
        setHasLoadedReal(true);
        setLastUpdatedAt(new Date().toISOString());
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        const detail = err instanceof Error ? err.message : "Request failed";
        setError(detail);
        // Phase 2A: in production we MUST NOT silently substitute fake
        // data for failed live calls. The error stays surfaced; data
        // remains at the initial mockFallback (which the page-level
        // ``error`` check should hide), and isMock=true so banners fire.
        if (!disableMockOnError) {
          setData(mockFallback);
        }
        setIsMock(true);
      })
      .finally(() => {
        if (cancelled) return;
        setIsLoading(false);
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [alwaysMock, reload, ...deps]);

  return {
    data,
    isLoading,
    error,
    isMock,
    lastUpdatedAt,
    // Stale only makes sense once we've shown real data at least once.
    stale: error != null && hasLoadedReal,
    hasLoadedReal,
    refetch: () => setReload((r) => r + 1),
  };
}
