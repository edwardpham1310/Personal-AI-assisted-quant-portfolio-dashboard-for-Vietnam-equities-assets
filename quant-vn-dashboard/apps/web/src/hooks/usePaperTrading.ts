"use client";

import { useCallback, useEffect, useState } from "react";
import { ApiError, useApi } from "@/lib/api";

// ── Types mirror backend Pydantic ────────────────────────────────────────

export type Side = "BUY" | "SELL";
export type PaperOrderType = "MARKET" | "LIMIT";
export type PaperOrderStatus =
  | "DRAFT"
  | "SUBMITTED"
  | "FILLED"
  | "PARTIALLY_FILLED"
  | "REJECTED"
  | "CANCELLED";
export type SourceType = "MANUAL" | "RECOMMENDATION" | "STRATEGY";

export type PaperAccount = {
  id: string;
  user_id: string;
  name: string;
  starting_cash: number;
  current_cash: number;
  currency: string;
  created_at: string | null;
  updated_at: string | null;
};

export type PaperPosition = {
  id: string | null;
  user_id: string;
  paper_account_id: string;
  symbol: string;
  quantity: number;
  sellable_quantity: number;
  pending_quantity: number;
  avg_cost: number;
  market_price: number | null;
  market_value: number | null;
  unrealized_pnl: number | null;
  updated_at: string | null;
};

export type PaperOrder = {
  id: string;
  paper_account_id: string;
  source_type: SourceType;
  source_id: string | null;
  symbol: string;
  side: Side;
  order_type: PaperOrderType;
  quantity: number;
  limit_price: number | null;
  status: PaperOrderStatus;
  rejection_reason: string | null;
  created_at: string | null;
};

export type PaperFill = {
  id: string;
  paper_account_id: string;
  paper_order_id: string;
  symbol: string;
  side: Side;
  quantity: number;
  fill_price: number;
  gross_value: number;
  brokerage_fee: number;
  vat: number;
  sell_tax: number;
  slippage: number;
  net_cash_impact: number;
  filled_at: string;
};

export type PaperEquityPoint = {
  id: string | null;
  paper_account_id: string;
  timestamp: string;
  cash: number;
  pending_cash: number;
  stock_value: number;
  total_equity: number;
  drawdown: number;
};

export type PaperAccountSummary = {
  account: PaperAccount;
  cash: number;
  pending_cash: number;
  stock_value: number;
  total_equity: number;
  realized_pnl: number;
  unrealized_pnl: number;
  drawdown: number;
  open_orders: number;
  positions: PaperPosition[];
  data_status: "FRESH" | "DATA_UNAVAILABLE";
};

export type PaperOrderResult = {
  order: PaperOrder;
  fill: PaperFill | null;
  rejection_reason: string | null;
};

// ── Hooks ────────────────────────────────────────────────────────────────

export function usePaperAccounts() {
  const api = useApi();
  const [data, setData] = useState<PaperAccount[]>([]);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const rows = await api<PaperAccount[]>("/paper/accounts");
      setData(rows);
    } finally {
      setLoading(false);
    }
  }, [api]);

  const create = useCallback(
    async (body: { name: string; starting_cash: number; currency?: string }) => {
      const row = await api<PaperAccount>("/paper/accounts", {
        method: "POST",
        body: JSON.stringify({ currency: "VND", ...body }),
      });
      await refresh();
      return row;
    },
    [api, refresh],
  );

  useEffect(() => {
    void refresh();
  }, [refresh]);

  return { data, loading, refresh, create };
}

export function usePaperSummary(accountId: string | null) {
  const api = useApi();
  const [data, setData] = useState<PaperAccountSummary | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    if (!accountId) return;
    setLoading(true);
    setError(null);
    try {
      const row = await api<PaperAccountSummary>(`/paper/accounts/${accountId}/summary`);
      setData(row);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load summary.");
    } finally {
      setLoading(false);
    }
  }, [api, accountId]);

  useEffect(() => {
    if (accountId) void refresh();
  }, [accountId, refresh]);

  return { data, loading, error, refresh };
}

export function usePaperOrdersAndFills(accountId: string | null) {
  const api = useApi();
  const [orders, setOrders] = useState<PaperOrder[]>([]);
  const [fills, setFills] = useState<PaperFill[]>([]);

  const refresh = useCallback(async () => {
    if (!accountId) return;
    const [o, f] = await Promise.all([
      api<PaperOrder[]>(`/paper/accounts/${accountId}/orders`),
      api<PaperFill[]>(`/paper/accounts/${accountId}/fills`),
    ]);
    setOrders(o);
    setFills(f);
  }, [api, accountId]);

  useEffect(() => {
    if (accountId) void refresh();
  }, [accountId, refresh]);

  return { orders, fills, refresh };
}

export function usePaperEquityCurve(accountId: string | null) {
  const api = useApi();
  const [data, setData] = useState<PaperEquityPoint[]>([]);

  const refresh = useCallback(async () => {
    if (!accountId) return;
    const rows = await api<PaperEquityPoint[]>(`/paper/accounts/${accountId}/equity-curve`);
    setData(rows);
  }, [api, accountId]);

  useEffect(() => {
    if (accountId) void refresh();
  }, [accountId, refresh]);

  return { data, refresh };
}

export function usePaperOrderActions(accountId: string | null) {
  const api = useApi();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [lastResult, setLastResult] = useState<PaperOrderResult | null>(null);

  const submit = useCallback(
    async (payload: {
      symbol: string;
      side: Side;
      order_type: PaperOrderType;
      quantity: number;
      limit_price?: number | null;
    }): Promise<PaperOrderResult | null> => {
      if (!accountId) return null;
      setBusy(true);
      setError(null);
      try {
        const r = await api<PaperOrderResult>(`/paper/accounts/${accountId}/orders`, {
          method: "POST",
          body: JSON.stringify(payload),
        });
        setLastResult(r);
        return r;
      } catch (e) {
        const msg =
          e instanceof ApiError
            ? `${e.status}: ${e.detail}`
            : e instanceof Error
              ? e.message
              : "Submit failed.";
        setError(msg);
        return null;
      } finally {
        setBusy(false);
      }
    },
    [api, accountId],
  );

  const runRecommendation = useCallback(
    async (payload: {
      symbol: string;
      side: Side;
      quantity: number;
      limit_price?: number | null;
      recommendation_id?: string | null;
    }): Promise<PaperOrderResult | null> => {
      if (!accountId) return null;
      setBusy(true);
      setError(null);
      try {
        const r = await api<PaperOrderResult>(`/paper/accounts/${accountId}/run-recommendation`, {
          method: "POST",
          body: JSON.stringify(payload),
        });
        setLastResult(r);
        return r;
      } catch (e) {
        const msg =
          e instanceof ApiError
            ? `${e.status}: ${e.detail}`
            : e instanceof Error
              ? e.message
              : "Run failed.";
        setError(msg);
        return null;
      } finally {
        setBusy(false);
      }
    },
    [api, accountId],
  );

  return { busy, error, lastResult, submit, runRecommendation };
}
