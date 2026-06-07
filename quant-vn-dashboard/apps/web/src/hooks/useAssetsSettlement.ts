"use client";

import { useApi } from "@/lib/api";
import { usePollingResource } from "./usePollingResource";

export type SettlementAlert = {
  settlement_date: string;
  symbol: string;
  side: "BUY" | "SELL";
  kind: "CASH_IN" | "SHARES_IN";
  quantity: number;
  amount?: number | null;
  days_until: number;
};

export type Settlement = {
  alerts: SettlementAlert[];
  pending_count: number;
  pending_cash: number;
  as_of?: string | null;
};

const POLL_MS = 60_000;

/**
 * GET /assets/settlement — pending T+2 settlements for the default account,
 * ascending by settlement date. Derived from real trade ``settlement_date``s;
 * honest-empty when there are none.
 */
export function useAssetsSettlement() {
  const api = useApi();
  const resource = usePollingResource<Settlement>({
    fetcher: () => api<Settlement>("/assets/settlement"),
    intervalMs: POLL_MS,
  });
  return {
    data: resource.data,
    loading: resource.loading,
    error: resource.error,
    refresh: resource.refresh,
  };
}
