"use client";

import { useCallback, useEffect, useState } from "react";
import { ApiError, useApi } from "@/lib/api";

// ── Types mirroring the backend Pydantic models ──────────────────────────

export type Side = "BUY" | "SELL";
export type OrderType = "LIMIT" | "MARKET" | "ATO" | "ATC" | "MTL";
export type ValidationStatus = "VALID" | "WARN" | "REJECTED";

export type TradingAccount = {
  id: string;
  user_id: string;
  broker: string;
  account_number_masked: string;
  account_alias: string | null;
  read_only_enabled: boolean;
  trading_enabled: boolean;
  created_at: string | null;
  updated_at: string | null;
};

export type CashBalance = {
  account_id: string;
  cash_balance: number;
  buying_power: number;
  withdrawable_cash: number;
  pending_cash: number;
  currency: string;
  as_of: string;
};

export type StockPosition = {
  account_id: string;
  symbol: string;
  exchange: string | null;
  quantity: number;
  sellable_quantity: number;
  pending_quantity: number;
  avg_cost: number;
  market_price: number | null;
  market_value: number | null;
  unrealized_pnl: number | null;
  as_of: string;
};

export type OrderPreviewRequest = {
  account_id: string;
  symbol: string;
  side: Side;
  quantity: number;
  limit_price: number;
  order_type: OrderType;
};

export type OrderPreviewResult = {
  symbol: string;
  side: Side;
  quantity: number;
  order_type: OrderType;
  limit_price: number;
  estimated_value: number;
  estimated_fees: number;
  estimated_tax: number;
  estimated_vat: number;
  estimated_slippage: number;
  total_cash_required: number | null;
  net_sell_proceeds: number | null;
  settlement_date: string | null;
  validation_status: ValidationStatus;
  warnings: string[];
  rejection_reasons: string[];
  is_live_order_submission_enabled: boolean;
};

// ── Hooks ─────────────────────────────────────────────────────────────────

export function useTradingAccounts() {
  const api = useApi();
  const [data, setData] = useState<TradingAccount[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const rows = await api<TradingAccount[]>("/trading");
      setData(rows);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load accounts.");
    } finally {
      setLoading(false);
    }
  }, [api]);

  const create = useCallback(
    async (
      payload: { account_number: string; account_alias?: string; broker?: string },
    ) => {
      const row = await api<TradingAccount>("/trading/accounts", {
        method: "POST",
        body: JSON.stringify({ broker: "SSI", ...payload }),
      });
      await refresh();
      return row;
    },
    [api, refresh],
  );

  useEffect(() => {
    void refresh();
  }, [refresh]);

  return { data, loading, error, refresh, create };
}

export function useCashBalance(accountId: string | null) {
  const api = useApi();
  const [data, setData] = useState<CashBalance | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    if (!accountId) return;
    setLoading(true);
    setError(null);
    try {
      const row = await api<CashBalance>(`/trading/cash?account_id=${accountId}`);
      setData(row);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load cash.");
    } finally {
      setLoading(false);
    }
  }, [api, accountId]);

  useEffect(() => {
    if (accountId) void refresh();
  }, [accountId, refresh]);

  return { data, loading, error, refresh };
}

export function useStockPositions(accountId: string | null) {
  const api = useApi();
  const [data, setData] = useState<StockPosition[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    if (!accountId) return;
    setLoading(true);
    setError(null);
    try {
      const rows = await api<StockPosition[]>(
        `/trading/positions?account_id=${accountId}`,
      );
      setData(rows);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load positions.");
    } finally {
      setLoading(false);
    }
  }, [api, accountId]);

  useEffect(() => {
    if (accountId) void refresh();
  }, [accountId, refresh]);

  return { data, loading, error, refresh };
}

export function useOrderPreview() {
  const api = useApi();
  const [result, setResult] = useState<OrderPreviewResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = useCallback(
    async (payload: OrderPreviewRequest) => {
      setLoading(true);
      setError(null);
      try {
        const r = await api<OrderPreviewResult>("/trading/order-preview", {
          method: "POST",
          body: JSON.stringify(payload),
        });
        setResult(r);
        return r;
      } catch (e) {
        const msg =
          e instanceof ApiError
            ? `${e.status}: ${e.detail}`
            : e instanceof Error
              ? e.message
              : "Preview failed.";
        setError(msg);
        return null;
      } finally {
        setLoading(false);
      }
    },
    [api],
  );

  const clear = useCallback(() => {
    setResult(null);
    setError(null);
  }, []);

  return { result, loading, error, submit, clear };
}
