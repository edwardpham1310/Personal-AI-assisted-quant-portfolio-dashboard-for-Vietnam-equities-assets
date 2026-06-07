"use client";

import { useCallback } from "react";
import { useApi } from "@/lib/api";
import { usePollingResource } from "./usePollingResource";

export type AlertCondition =
  | "price_above"
  | "price_below"
  | "pct_change_above"
  | "pct_change_below";

export type AlertWithStatus = {
  id: string;
  user_id: string;
  symbol: string;
  exchange: string;
  condition: AlertCondition;
  threshold: number;
  note: string | null;
  is_active: boolean;
  last_triggered_at: string | null;
  created_at: string | null;
  updated_at: string | null;
  evaluated: boolean;
  currently_triggered: boolean | null;
  observed_price: number | null;
  observed_change_pct: number | null;
  quote_stale: boolean;
  quote_as_of: string | null;
};

export type AlertList = {
  alerts: AlertWithStatus[];
  count: number;
  triggered_count: number;
  as_of: string | null;
  disclaimer: string;
};

export type AlertCreateBody = {
  symbol: string;
  condition: AlertCondition;
  threshold: number;
  exchange?: string;
  note?: string | null;
};

/**
 * GET /alerts plus create/update/delete mutations. Alerts are research
 * notifications (price / day-change thresholds) — evaluating them never places
 * an order. The list is evaluated server-side against the latest cached quote.
 */
export function useAlerts() {
  const api = useApi();
  const resource = usePollingResource<AlertList>({
    fetcher: () => api<AlertList>("/alerts"),
    intervalMs: 60_000,
  });

  const create = useCallback(
    (body: AlertCreateBody) =>
      api<AlertWithStatus>("/alerts", { method: "POST", body: JSON.stringify(body) }),
    [api],
  );
  const update = useCallback(
    (id: string, patch: Partial<Pick<AlertWithStatus, "condition" | "threshold" | "note" | "is_active">>) =>
      api(`/alerts/${id}`, { method: "PATCH", body: JSON.stringify(patch) }),
    [api],
  );
  const remove = useCallback(
    (id: string) => api(`/alerts/${id}`, { method: "DELETE" }),
    [api],
  );

  return {
    data: resource.data,
    loading: resource.loading,
    error: resource.error,
    refresh: resource.refresh,
    create,
    update,
    remove,
  };
}
