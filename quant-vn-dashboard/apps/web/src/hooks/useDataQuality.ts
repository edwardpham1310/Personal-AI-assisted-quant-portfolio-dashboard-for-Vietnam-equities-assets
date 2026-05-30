"use client";

import { useApi } from "@/lib/api";
import { usePollingResource } from "./usePollingResource";
import type { DataQualitySnapshot } from "./useSystemStatus";

const POLL_INTERVAL_MS = 60_000;

export function useDataQuality() {
  const api = useApi();
  return usePollingResource<DataQualitySnapshot>({
    fetcher: () => api<DataQualitySnapshot>("/system/data-quality"),
    intervalMs: POLL_INTERVAL_MS,
  });
}
