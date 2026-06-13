"use client";

import { useApi } from "@/lib/api";
import { isoDate, rangeStartDate, sortByTimeAsc, type RangeKey } from "@/lib/dateRange";
import { usePollingResource } from "./usePollingResource";

export type CashMovement = {
  date: string;
  settlement_date?: string | null;
  symbol: string;
  side: "BUY" | "SELL";
  gross: number;
  fees: number;
  amount: number; // signed: − on BUY, + on SELL
};

export type CashMovements = {
  movements: CashMovement[];
  net_cash_flow: number;
  as_of?: string | null;
  note?: string;
};

const POLL_MS = 60_000;

/**
 * GET /assets/cash-movements — trade-driven cash flows for the default account,
 * ascending by date, scoped to a calendar range. Real data only (no deposits/
 * withdrawals ledger exists — the backend says so in ``note``). Honest-empty
 * until trades exist.
 */
export function useAssetsCashMovements(range: RangeKey) {
  const api = useApi();
  const start = rangeStartDate(range);
  const qs = start ? `?start=${isoDate(start)}&end=${isoDate(new Date())}` : "";
  const resource = usePollingResource<CashMovements>({
    fetcher: async () => {
      const r = await api<CashMovements>(`/assets/cash-movements${qs}`);
      // Defensive ascending guard (backend already sorts).
      // Event series: multiple trades can share a date — sort ascending but do
      // NOT de-dupe (that would drop same-day movements).
      return { ...r, movements: sortByTimeAsc(r.movements ?? [], (m) => m.date) };
    },
    intervalMs: POLL_MS,
    deps: [qs],
  });
  return {
    data: resource.data,
    loading: resource.loading,
    error: resource.error,
    lastUpdatedAt: resource.lastUpdatedAt,
    stale: resource.stale,
    refresh: resource.refresh,
  };
}
