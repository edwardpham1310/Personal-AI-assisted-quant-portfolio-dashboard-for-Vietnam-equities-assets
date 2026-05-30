"use client";

import { useEffect, useState } from "react";

export type AsyncState<T> = {
  data: T;
  isLoading: boolean;
  error: string | null;
  /** True when ``data`` comes from the mock fallback rather than the live API. */
  isMock: boolean;
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
}: Options<T>): AsyncState<T> {
  const [data, setData] = useState<T>(mockFallback);
  const [isLoading, setIsLoading] = useState<boolean>(!alwaysMock);
  const [error, setError] = useState<string | null>(null);
  const [isMock, setIsMock] = useState<boolean>(alwaysMock);
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
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        const detail = err instanceof Error ? err.message : "Request failed";
        setError(detail);
        setData(mockFallback);
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
    refetch: () => setReload((r) => r + 1),
  };
}
