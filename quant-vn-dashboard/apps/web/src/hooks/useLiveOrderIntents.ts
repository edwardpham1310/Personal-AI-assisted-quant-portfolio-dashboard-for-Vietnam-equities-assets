"use client";

import { useCallback, useEffect, useState } from "react";
import { ApiError, useApi } from "@/lib/api";

// Types mirror schemas/live_orders.py.

export type LiveOrderIntentStatus =
  | "DRAFT"
  | "PREVIEWED"
  | "CONFIRM_REQUIRED"
  | "CONFIRMED"
  | "SUBMITTED"
  | "REJECTED"
  | "CANCELLED"
  | "FAILED";

export type ValidationStatus = "VALID" | "WARN" | "REJECTED";
export type Side = "BUY" | "SELL";
export type OrderType = "LIMIT" | "MARKET" | "ATO" | "ATC" | "MTL";
export type SourceType = "MANUAL" | "RECOMMENDATION" | "PAPER_COPY" | "STRATEGY";

export type LiveOrderIntent = {
  id: string;
  user_id: string;
  account_id: string;
  source_type: SourceType;
  source_id: string | null;
  symbol: string;
  side: Side;
  order_type: OrderType;
  quantity: number;
  limit_price: number | null;
  preview_id: string | null;
  status: LiveOrderIntentStatus;
  validation_snapshot: Record<string, unknown> | null;
  warnings: string[];
  rejection_reasons: string[];
  created_at: string | null;
  confirmed_at: string | null;
  submitted_at: string | null;
  updated_at: string | null;
};

export type GateStatus = {
  live_order_enabled: boolean;
  manual_confirm_enabled: boolean;
  read_only_disabled: boolean;
  not_using_mock: boolean;
  dry_run_disabled: boolean;
  all_open: boolean;
};

export type LiveOrderIntentResult = {
  intent: LiveOrderIntent;
  validation_status: ValidationStatus;
  rejection_reasons: string[];
  warnings: string[];
  is_live_submission_performed: boolean;
  is_dry_run: boolean;
  submission: unknown | null;
  gate_status: GateStatus;
};

export function useLiveOrderIntents(accountId: string | null) {
  const api = useApi();
  const [data, setData] = useState<LiveOrderIntent[]>([]);
  const [loading, setLoading] = useState(false);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const qs = accountId ? `?account_id=${accountId}` : "";
      const rows = await api<LiveOrderIntent[]>(
        `/trading/live-order-intents${qs}`,
      );
      setData(rows);
    } finally {
      setLoading(false);
    }
  }, [api, accountId]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  return { data, loading, refresh };
}

export function useLiveOrderActions(accountId: string | null) {
  const api = useApi();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [lastResult, setLastResult] = useState<LiveOrderIntentResult | null>(
    null,
  );

  function _setError(e: unknown) {
    const msg =
      e instanceof ApiError
        ? `${e.status}: ${e.detail}`
        : e instanceof Error
          ? e.message
          : "Action failed.";
    setError(msg);
  }

  const create = useCallback(
    async (body: {
      symbol: string;
      side: Side;
      order_type: OrderType;
      quantity: number;
      limit_price?: number | null;
      source_type?: SourceType;
    }): Promise<LiveOrderIntent | null> => {
      if (!accountId) return null;
      setBusy(true);
      setError(null);
      try {
        const row = await api<LiveOrderIntent>(
          "/trading/live-order-intents",
          {
            method: "POST",
            body: JSON.stringify({
              account_id: accountId,
              source_type: "MANUAL",
              ...body,
            }),
          },
        );
        return row;
      } catch (e) {
        _setError(e);
        return null;
      } finally {
        setBusy(false);
      }
    },
    [api, accountId],
  );

  const preview = useCallback(
    async (intentId: string): Promise<LiveOrderIntentResult | null> => {
      setBusy(true);
      setError(null);
      try {
        const r = await api<LiveOrderIntentResult>(
          `/trading/live-order-intents/${intentId}/preview`,
          { method: "POST", body: JSON.stringify({}) },
        );
        setLastResult(r);
        return r;
      } catch (e) {
        _setError(e);
        return null;
      } finally {
        setBusy(false);
      }
    },
    [api],
  );

  const requestConfirmation = useCallback(
    async (intentId: string): Promise<LiveOrderIntentResult | null> => {
      setBusy(true);
      setError(null);
      try {
        const r = await api<LiveOrderIntentResult>(
          `/trading/live-order-intents/${intentId}/request-confirmation`,
          { method: "POST", body: JSON.stringify({}) },
        );
        setLastResult(r);
        return r;
      } catch (e) {
        _setError(e);
        return null;
      } finally {
        setBusy(false);
      }
    },
    [api],
  );

  const confirm = useCallback(
    async (
      intentId: string,
      risk_acknowledged: boolean,
    ): Promise<LiveOrderIntentResult | null> => {
      setBusy(true);
      setError(null);
      try {
        const r = await api<LiveOrderIntentResult>(
          `/trading/live-order-intents/${intentId}/confirm`,
          { method: "POST", body: JSON.stringify({ risk_acknowledged }) },
        );
        setLastResult(r);
        return r;
      } catch (e) {
        _setError(e);
        return null;
      } finally {
        setBusy(false);
      }
    },
    [api],
  );

  const submit = useCallback(
    async (intentId: string): Promise<LiveOrderIntentResult | null> => {
      setBusy(true);
      setError(null);
      try {
        const r = await api<LiveOrderIntentResult>(
          `/trading/live-order-intents/${intentId}/submit`,
          { method: "POST", body: JSON.stringify({}) },
        );
        setLastResult(r);
        return r;
      } catch (e) {
        _setError(e);
        return null;
      } finally {
        setBusy(false);
      }
    },
    [api],
  );

  const cancel = useCallback(
    async (intentId: string): Promise<LiveOrderIntentResult | null> => {
      setBusy(true);
      setError(null);
      try {
        const r = await api<LiveOrderIntentResult>(
          `/trading/live-order-intents/${intentId}/cancel`,
          { method: "POST", body: JSON.stringify({}) },
        );
        setLastResult(r);
        return r;
      } catch (e) {
        _setError(e);
        return null;
      } finally {
        setBusy(false);
      }
    },
    [api],
  );

  return {
    busy,
    error,
    lastResult,
    create,
    preview,
    requestConfirmation,
    confirm,
    submit,
    cancel,
  };
}
