"use client";

import { useCallback, useEffect, useState } from "react";
import { ApiError, useApi } from "@/lib/api";
import { createClient } from "@/lib/supabase/client";

// ── Types mirror backend Pydantic ────────────────────────────────────────

export type AutoTradeMode = "OFF" | "PAPER_ONLY" | "LIVE_MANUAL_CONFIRM" | "LIVE_AUTO";

export type ValidationStatus = "VALID" | "REJECTED";

export type AutoTradeSettings = {
  id: string | null;
  user_id: string;
  account_id: string;
  mode: AutoTradeMode;
  enabled: boolean;
  max_capital_vnd: number;
  max_order_value_vnd: number;
  max_orders_per_day: number;
  max_daily_loss_vnd: number;
  max_position_weight: number;
  max_sector_weight: number;
  allowed_strategies: string[];
  allowed_symbols: string[];
  allowed_watchlists: string[];
  require_manual_confirm: boolean;
  require_reauth: boolean;
  last_reauth_at: string | null;
  risk_acknowledged_at: string | null;
  created_at: string | null;
  updated_at: string | null;
};

export type AutoTradeState = {
  id: string | null;
  user_id: string;
  account_id: string;
  mode: AutoTradeMode;
  is_running: boolean;
  last_started_at: string | null;
  last_stopped_at: string | null;
  emergency_stopped_at: string | null;
  emergency_stop_reason: string | null;
};

export type ModeTransitionResult = {
  account_id: string;
  mode: AutoTradeMode;
  validation_status: ValidationStatus;
  rejection_reasons: string[];
  is_live_execution_enabled: boolean;
  last_reauth_at: string | null;
  risk_acknowledged_at: string | null;
};

export type LiveAutoRequestResult = ModeTransitionResult & {
  next_step: "CONFIRM_RISK_ACKNOWLEDGEMENT" | "ABORT";
};

export type AutoTradeAuditEntry = {
  id: string;
  user_id: string;
  account_id: string | null;
  action: string;
  metadata: Record<string, unknown>;
  created_at: string;
};

export type AutoTradeSettingsUpdate = Partial<
  Omit<
    AutoTradeSettings,
    | "id"
    | "user_id"
    | "account_id"
    | "mode"
    | "enabled"
    | "last_reauth_at"
    | "risk_acknowledged_at"
    | "created_at"
    | "updated_at"
  >
>;

// ── Hooks ─────────────────────────────────────────────────────────────────

export function useAutoTradeSettings(accountId: string | null) {
  const api = useApi();
  const [data, setData] = useState<AutoTradeSettings | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    if (!accountId) return;
    setLoading(true);
    setError(null);
    try {
      const row = await api<AutoTradeSettings>(`/auto-trade/settings?account_id=${accountId}`);
      setData(row);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load settings.");
    } finally {
      setLoading(false);
    }
  }, [api, accountId]);

  const save = useCallback(
    async (patch: AutoTradeSettingsUpdate) => {
      if (!accountId) return null;
      const updated = await api<AutoTradeSettings>(`/auto-trade/settings?account_id=${accountId}`, {
        method: "PUT",
        body: JSON.stringify(patch),
      });
      setData(updated);
      return updated;
    },
    [api, accountId],
  );

  useEffect(() => {
    if (accountId) void refresh();
  }, [accountId, refresh]);

  return { data, loading, error, refresh, save };
}

export function useAutoTradeState(accountId: string | null) {
  const api = useApi();
  const [data, setData] = useState<AutoTradeState | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    if (!accountId) return;
    setLoading(true);
    setError(null);
    try {
      const row = await api<AutoTradeState>(`/auto-trade/state?account_id=${accountId}`);
      setData(row);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load state.");
    } finally {
      setLoading(false);
    }
  }, [api, accountId]);

  useEffect(() => {
    if (accountId) void refresh();
  }, [accountId, refresh]);

  return { data, loading, error, refresh };
}

export function useAutoTradeAuditLogs(accountId: string | null) {
  const api = useApi();
  const [data, setData] = useState<AutoTradeAuditEntry[]>([]);
  const [loading, setLoading] = useState(false);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const qs = accountId ? `?account_id=${accountId}` : "";
      const rows = await api<AutoTradeAuditEntry[]>(`/auto-trade/audit-logs${qs}`);
      setData(rows);
    } catch {
      // best-effort — audit table is operator-facing
    } finally {
      setLoading(false);
    }
  }, [api, accountId]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  return { data, loading, refresh };
}

// ── Mode-transition actions ──────────────────────────────────────────────

export function useAutoTradeActions(accountId: string | null) {
  const api = useApi();
  const [busy, setBusy] = useState(false);
  const [lastResult, setLastResult] = useState<ModeTransitionResult | LiveAutoRequestResult | null>(
    null,
  );
  const [error, setError] = useState<string | null>(null);

  const post = useCallback(
    async <T>(path: string, body: object) => {
      if (!accountId) return null;
      setBusy(true);
      setError(null);
      try {
        const r = await api<T>(path, {
          method: "POST",
          body: JSON.stringify({ account_id: accountId, ...body }),
        });
        return r;
      } catch (e) {
        const msg =
          e instanceof ApiError
            ? `${e.status}: ${e.detail}`
            : e instanceof Error
              ? e.message
              : "Action failed.";
        setError(msg);
        return null;
      } finally {
        setBusy(false);
      }
    },
    [api, accountId],
  );

  const enablePaper = useCallback(async () => {
    const r = await post<ModeTransitionResult>("/auto-trade/enable-paper", {});
    if (r) setLastResult(r);
    return r;
  }, [post]);

  const enableManualConfirm = useCallback(async () => {
    const r = await post<ModeTransitionResult>("/auto-trade/enable-manual-confirm", {});
    if (r) setLastResult(r);
    return r;
  }, [post]);

  const requestLiveAuto = useCallback(async () => {
    const r = await post<LiveAutoRequestResult>("/auto-trade/request-live-auto-enable", {});
    if (r) setLastResult(r);
    return r;
  }, [post]);

  const confirmLiveAuto = useCallback(
    async (risk_acknowledged: boolean) => {
      const r = await post<ModeTransitionResult>("/auto-trade/confirm-live-auto-enable", {
        risk_acknowledged,
      });
      if (r) setLastResult(r);
      return r;
    },
    [post],
  );

  const disable = useCallback(async () => {
    const r = await post<ModeTransitionResult>("/auto-trade/disable", {});
    if (r) setLastResult(r);
    return r;
  }, [post]);

  const emergencyStop = useCallback(
    async (reason: string) => {
      const r = await post<ModeTransitionResult>("/auto-trade/emergency-stop", { reason });
      if (r) setLastResult(r);
      return r;
    },
    [post],
  );

  return {
    busy,
    error,
    lastResult,
    enablePaper,
    enableManualConfirm,
    requestLiveAuto,
    confirmLiveAuto,
    disable,
    emergencyStop,
  };
}

// ── Re-auth (Supabase signInWithPassword + backend stamp) ────────────────

export type ReauthOutcome = { ok: true; last_reauth_at: string } | { ok: false; error: string };

export function useAutoTradeReauth(accountId: string | null) {
  const api = useApi();
  const [busy, setBusy] = useState(false);

  const reauth = useCallback(
    async (email: string, password: string): Promise<ReauthOutcome> => {
      if (!accountId) return { ok: false, error: "No account selected." };
      setBusy(true);
      try {
        // Frontend-only password verification via Supabase. The new
        // session JWT carries a fresh `iat` claim — the backend reads
        // that to prove the re-auth happened, without ever seeing the
        // password.
        const supabase = createClient();
        const { error: authErr } = await supabase.auth.signInWithPassword({
          email,
          password,
        });
        if (authErr) {
          return { ok: false, error: authErr.message };
        }
        // Backend stamps last_reauth_at based on the fresh JWT iat.
        const r = await api<{ ok: boolean; last_reauth_at: string }>(
          `/auto-trade/reauth?account_id=${accountId}`,
          { method: "POST", body: JSON.stringify({}) },
        );
        return { ok: true, last_reauth_at: r.last_reauth_at };
      } catch (e) {
        const msg =
          e instanceof ApiError
            ? `${e.status}: ${e.detail}`
            : e instanceof Error
              ? e.message
              : "Re-auth failed.";
        return { ok: false, error: msg };
      } finally {
        setBusy(false);
      }
    },
    [api, accountId],
  );

  return { busy, reauth };
}
