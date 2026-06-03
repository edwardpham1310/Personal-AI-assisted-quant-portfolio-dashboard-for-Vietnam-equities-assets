"use client";

import { useApi } from "@/lib/api";
import { isProductionBuild } from "@/lib/env";
import {
  MOCK_DATA_QUALITY,
  MOCK_RISK_ALERTS,
  MOCK_SETTLEMENT_ALERTS,
  type DataQualityStatus,
  type RiskAlert,
  type SettlementAlert,
} from "@/lib/mock/portfolio";
import { useAsyncResource } from "./useAsyncResource";

type LiveStatus = {
  cache_backend: string;
  poller_enabled: boolean;
  poller_running: boolean;
  last_poll: { ts: string; ok: boolean; symbol_count: number; error: string | null } | null;
  quote_stale_after_seconds: number;
};

export function useDataQualityStatus() {
  const api = useApi();
  return useAsyncResource<DataQualityStatus>({
    fetcher: async () => {
      const status = await api<LiveStatus>("/market/live/status");
      const lag = status.last_poll
        ? Math.max(0, Math.round((Date.now() - new Date(status.last_poll.ts).getTime()) / 60_000))
        : 999;
      const tag: DataQualityStatus["status"] = !status.poller_enabled
        ? "WARN"
        : status.last_poll?.ok === false
          ? "ERROR"
          : lag > 5
            ? "WARN"
            : "OK";
      return {
        status: tag,
        ingest_lag_minutes: lag,
        issues_24h: status.last_poll?.error ? 1 : 0,
        note: status.poller_enabled
          ? `Cache: ${status.cache_backend}. Last poll ${status.last_poll?.ts ?? "never"}`
          : "Poller disabled — set ENABLE_MARKET_POLLER=true.",
      };
    },
    mockFallback: MOCK_DATA_QUALITY,
  });
}

// Risk/settlement alert endpoints are not wired yet. In production resolve to
// an EMPTY list (the panels render an honest empty state) — never synthetic
// alerts. In development keep the mock for UI work (shown with a "Mock" badge).
// TODO: point these fetchers at real endpoints once they exist.
export function useRiskAlerts() {
  return useAsyncResource<RiskAlert[]>({
    fetcher: () => Promise.resolve([]),
    mockFallback: MOCK_RISK_ALERTS,
    alwaysMock: !isProductionBuild,
  });
}

export function useSettlementAlerts() {
  return useAsyncResource<SettlementAlert[]>({
    fetcher: () => Promise.resolve([]),
    mockFallback: MOCK_SETTLEMENT_ALERTS,
    alwaysMock: !isProductionBuild,
  });
}
