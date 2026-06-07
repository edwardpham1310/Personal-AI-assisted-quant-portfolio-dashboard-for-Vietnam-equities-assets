"use client";

import { useCallback, useEffect, useState } from "react";
import { useApi } from "@/lib/api";

export type BrokerCash = {
  cash_balance: number;
  buying_power: number;
  withdrawable_cash: number;
  pending_cash: number;
  currency: string;
  as_of: string;
};

export type BrokerPosition = {
  symbol: string;
  quantity: number;
  sellable_quantity: number;
  avg_cost: number;
  market_price: number | null;
  market_value: number | null;
  unrealized_pnl: number | null;
};

/** Shape of POST /portfolio/sync/ssi — the read-only SSI account snapshot. */
export type BrokerSnapshot = {
  connected: boolean;
  status_code: string;
  mock: boolean;
  account_masked?: string | null;
  cash?: BrokerCash | null;
  positions?: BrokerPosition[];
  note?: string | null;
};

/**
 * Read-only SSI broker account snapshot for the dashboard.
 *
 * Single call to `POST /portfolio/sync/ssi`, which resolves the SSI account
 * SERVER-SIDE from config and returns status + cash + positions in one shape.
 * It is read-only (no DB writes, no order path). Real cash/positions appear
 * only when `connected` is true (a genuinely configured read-only SSI
 * provider); in mock/dev or when unconfigured, the backend returns
 * `connected:false` with no balances — fabricated numbers never reach the UI.
 */
export function useBrokerAccount() {
  const api = useApi();
  const [snapshot, setSnapshot] = useState<BrokerSnapshot | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const snap = await api<BrokerSnapshot>("/portfolio/sync/ssi", { method: "POST" });
      setSnapshot(snap);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load broker status.");
    } finally {
      setLoading(false);
    }
  }, [api]);

  useEffect(() => {
    void load();
  }, [load]);

  return { snapshot, loading, error, refresh: load };
}
