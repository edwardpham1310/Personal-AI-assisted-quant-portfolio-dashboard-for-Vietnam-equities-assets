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
// Dev shows mock (badged); production resolves to real data — never synthetic
// alerts. Honest-empty when the portfolio is calm / nothing settles.
type RiskComponent = { label: string; available: boolean; score?: number | null; detail?: string | null };
type RiskScorePayload = { score: number | null; band: string; components: RiskComponent[] };

const RISK_COMPONENT_ALERT_MIN = 70; // 0..100 subscore at/above which we surface it

/**
 * Risk alerts derived from the real, explainable risk score
 * (`GET /portfolio/risk-score`): an elevated/high band plus any available
 * component scoring >= 70. Empty when risk is low/moderate or unavailable.
 */
export function useRiskAlerts() {
  const api = useApi();
  return useAsyncResource<RiskAlert[]>({
    fetcher: async () => {
      const r = await api<RiskScorePayload>("/portfolio/risk-score");
      const alerts: RiskAlert[] = [];
      const band = (r.band ?? "").toLowerCase();
      const scoreTxt = r.score != null ? ` (${Math.round(r.score)}/100)` : "";
      if (band === "high") {
        alerts.push({ severity: "error", message: `Portfolio risk is high${scoreTxt}` });
      } else if (band === "elevated") {
        alerts.push({ severity: "warning", message: `Portfolio risk is elevated${scoreTxt}` });
      }
      for (const c of r.components ?? []) {
        if (c.available && c.score != null && c.score >= RISK_COMPONENT_ALERT_MIN) {
          alerts.push({ severity: "warning", message: c.detail ?? c.label });
        }
      }
      return alerts;
    },
    mockFallback: MOCK_RISK_ALERTS,
    alwaysMock: !isProductionBuild,
  });
}

type BackendSettlement = {
  settlement_date: string;
  symbol: string;
  kind: string; // CASH_IN | SHARES_IN
  quantity: number;
  amount: number | null;
  days_until: number;
};
type SettlementResponse = { alerts: BackendSettlement[] };

/**
 * Pending T+2 settlements from the real endpoint (`GET /assets/settlement`).
 * Honest-empty when nothing is settling.
 */
export function useSettlementAlerts() {
  const api = useApi();
  return useAsyncResource<SettlementAlert[]>({
    fetcher: async () => {
      const r = await api<SettlementResponse>("/assets/settlement");
      return (r.alerts ?? []).map((a) => {
        const when = a.days_until > 0 ? `in ${a.days_until}d` : "today";
        const what =
          a.kind === "CASH_IN"
            ? `cash settles ${when}`
            : `${a.quantity.toLocaleString()} shares settle ${when}`;
        return { ts: a.settlement_date, message: `${a.symbol}: ${what}` };
      });
    },
    mockFallback: MOCK_SETTLEMENT_ALERTS,
    alwaysMock: !isProductionBuild,
  });
}
