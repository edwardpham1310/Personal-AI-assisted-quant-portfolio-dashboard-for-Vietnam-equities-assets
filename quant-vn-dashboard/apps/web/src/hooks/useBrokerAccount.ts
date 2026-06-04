"use client";

import { useCallback, useEffect, useState } from "react";
import { useApi } from "@/lib/api";

/** Shape of GET /trading/status (provider snapshot + the SSI env flags). */
export type BrokerStatus = {
  name: string;
  mock: boolean;
  read_only: boolean;
  order_placement_enabled: boolean;
  status_code: string;
  note?: string | null;
  ssi_trading_use_mock: boolean;
  ssi_trading_read_only: boolean;
  ssi_trading_order_placement_enabled: boolean;
};

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

type TradingAccount = { id: string; broker: string };

/**
 * Read-only SSI broker account state for the dashboard.
 *
 * Honest by construction: live cash/positions are fetched ONLY when the
 * provider reports a real, configured, read-only SSI connection
 * (`status_code === "READ_ONLY"` and not mock). In mock/dev or when SSI is
 * unconfigured, no balances are fetched — so fabricated mock numbers can never
 * reach the UI as if they were real.
 */
export function useBrokerAccount() {
  const api = useApi();
  const [status, setStatus] = useState<BrokerStatus | null>(null);
  const [cash, setCash] = useState<BrokerCash | null>(null);
  const [positions, setPositions] = useState<BrokerPosition[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const st = await api<BrokerStatus>("/trading/status");
      setStatus(st);
      // Only fetch real balances from a genuinely connected, read-only SSI
      // provider. Never surface mock data as real.
      const isLive = !st.mock && st.status_code === "READ_ONLY";
      if (isLive) {
        const accounts = await api<TradingAccount[]>("/trading");
        const ssi = accounts.find((a) => a.broker === "SSI") ?? accounts[0];
        if (ssi) {
          const [c, p] = await Promise.all([
            api<BrokerCash>(`/trading/cash?account_id=${encodeURIComponent(ssi.id)}`),
            api<BrokerPosition[]>(`/trading/positions?account_id=${encodeURIComponent(ssi.id)}`),
          ]);
          setCash(c);
          setPositions(p);
        }
      } else {
        setCash(null);
        setPositions([]);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load broker status.");
    } finally {
      setLoading(false);
    }
  }, [api]);

  useEffect(() => {
    void load();
  }, [load]);

  return { status, cash, positions, loading, error, refresh: load };
}
