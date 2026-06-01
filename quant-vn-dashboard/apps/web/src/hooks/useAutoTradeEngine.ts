"use client";

import { useCallback, useEffect, useState } from "react";
import { ApiError, useApi } from "@/lib/api";

// Types mirror schemas/auto_trade_engine.py

export type RunStatus =
  | "STARTED"
  | "RUNNING"
  | "PAUSED"
  | "STOPPED"
  | "EMERGENCY_STOPPED"
  | "FAILED";

export type AutoTradeMode =
  | "OFF"
  | "PAPER_ONLY"
  | "LIVE_MANUAL_CONFIRM"
  | "LIVE_AUTO";

export type AutoTradeRun = {
  id: string;
  user_id: string;
  account_id: string;
  mode: AutoTradeMode;
  strategy_id: string;
  status: RunStatus;
  started_at: string | null;
  stopped_at: string | null;
  metadata: Record<string, unknown>;
};

export type DecisionOutcome =
  | "DISPATCHED_PAPER"
  | "DISPATCHED_MANUAL_CONFIRM"
  | "DISPATCHED_LIVE_DRY_RUN"
  | "DISPATCHED_LIVE"
  | "SKIPPED_BY_RISK"
  | "SKIPPED_NOT_ALLOWED"
  | "SKIPPED_COOLDOWN"
  | "SKIPPED_KILL_SWITCH"
  | "SKIPPED_MARKET_CLOSED"
  | "SKIPPED_DATA_STALE"
  | "SKIPPED_NOT_RECOMMENDED";

export type AutoTradeDecision = {
  id: string;
  user_id: string;
  account_id: string;
  run_id: string;
  symbol: string;
  recommendation_id: string | null;
  action: string;
  decision: DecisionOutcome;
  reason: Record<string, unknown>;
  risk_snapshot: Record<string, unknown>;
  created_at: string;
};

export type AutoTradeOrder = {
  id: string;
  user_id: string;
  account_id: string;
  run_id: string;
  decision_id: string;
  live_order_intent_id: string | null;
  paper_order_id: string | null;
  mode: "PAPER" | "MANUAL_CONFIRM" | "LIVE_DRY_RUN" | "LIVE";
  status: string;
  created_at: string;
};

export type AutoTradeRiskCounter = {
  id: string;
  user_id: string;
  account_id: string;
  trading_date: string;
  orders_count: number;
  gross_order_value: number;
  realized_loss: number;
  unrealized_loss: number;
  daily_loss: number;
  updated_at: string;
};

// ── Hooks ────────────────────────────────────────────────────────────────

export function useAutoTradeRuns(accountId: string | null) {
  const api = useApi();
  const [data, setData] = useState<AutoTradeRun[]>([]);
  const [loading, setLoading] = useState(false);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const qs = accountId ? `?account_id=${accountId}` : "";
      const rows = await api<AutoTradeRun[]>(`/auto-trade/runs${qs}`);
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

export function useAutoTradeDecisions(
  runId: string | null,
  accountId: string | null,
) {
  const api = useApi();
  const [data, setData] = useState<AutoTradeDecision[]>([]);

  const refresh = useCallback(async () => {
    const params = new URLSearchParams();
    if (runId) params.set("run_id", runId);
    if (accountId) params.set("account_id", accountId);
    const qs = params.toString() ? `?${params.toString()}` : "";
    const rows = await api<AutoTradeDecision[]>(
      `/auto-trade/decisions${qs}`,
    );
    setData(rows);
  }, [api, runId, accountId]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  return { data, refresh };
}

export function useAutoTradeEngineOrders(
  runId: string | null,
  accountId: string | null,
) {
  const api = useApi();
  const [data, setData] = useState<AutoTradeOrder[]>([]);

  const refresh = useCallback(async () => {
    const params = new URLSearchParams();
    if (runId) params.set("run_id", runId);
    if (accountId) params.set("account_id", accountId);
    const qs = params.toString() ? `?${params.toString()}` : "";
    const rows = await api<AutoTradeOrder[]>(`/auto-trade/orders${qs}`);
    setData(rows);
  }, [api, runId, accountId]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  return { data, refresh };
}

export function useAutoTradeRiskCounters(accountId: string | null) {
  const api = useApi();
  const [data, setData] = useState<AutoTradeRiskCounter[]>([]);

  const refresh = useCallback(async () => {
    const qs = accountId ? `?account_id=${accountId}` : "";
    const rows = await api<AutoTradeRiskCounter[]>(
      `/auto-trade/risk-counters${qs}`,
    );
    setData(rows);
  }, [api, accountId]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  return { data, refresh };
}

// ── Actions ──────────────────────────────────────────────────────────────

export function useAutoTradeRunActions(accountId: string | null) {
  const api = useApi();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function _err(e: unknown) {
    setError(
      e instanceof ApiError
        ? `${e.status}: ${e.detail}`
        : e instanceof Error
          ? e.message
          : "Action failed.",
    );
  }

  const startRun = useCallback(
    async (
      strategy_id = "default",
    ): Promise<AutoTradeRun | null> => {
      if (!accountId) return null;
      setBusy(true);
      setError(null);
      try {
        return await api<AutoTradeRun>("/auto-trade/runs/start", {
          method: "POST",
          body: JSON.stringify({
            account_id: accountId,
            strategy_id,
          }),
        });
      } catch (e) {
        _err(e);
        return null;
      } finally {
        setBusy(false);
      }
    },
    [api, accountId],
  );

  const stopRun = useCallback(
    async (run_id: string): Promise<AutoTradeRun | null> => {
      setBusy(true);
      setError(null);
      try {
        return await api<AutoTradeRun>(
          `/auto-trade/runs/stop?run_id=${run_id}`,
          { method: "POST", body: JSON.stringify({}) },
        );
      } catch (e) {
        _err(e);
        return null;
      } finally {
        setBusy(false);
      }
    },
    [api],
  );

  const pauseRun = useCallback(
    async (run_id: string): Promise<AutoTradeRun | null> => {
      setBusy(true);
      setError(null);
      try {
        return await api<AutoTradeRun>(
          `/auto-trade/runs/pause?run_id=${run_id}`,
          { method: "POST", body: JSON.stringify({}) },
        );
      } catch (e) {
        _err(e);
        return null;
      } finally {
        setBusy(false);
      }
    },
    [api],
  );

  return { busy, error, startRun, stopRun, pauseRun };
}
