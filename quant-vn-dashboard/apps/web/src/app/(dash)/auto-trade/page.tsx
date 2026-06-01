"use client";

import { useMemo, useState } from "react";
import { Card } from "@/components/ui/Card";
import { Badge } from "@/components/ui/Badge";
import { formatVnd, formatNumber } from "@/lib/format";
import {
  useAutoTradeActions,
  useAutoTradeAuditLogs,
  useAutoTradeReauth,
  useAutoTradeSettings,
  useAutoTradeState,
  type AutoTradeMode,
} from "@/hooks/useAutoTrade";
import {
  useAutoTradeDecisions,
  useAutoTradeEngineOrders,
  useAutoTradeRiskCounters,
  useAutoTradeRunActions,
  useAutoTradeRuns,
} from "@/hooks/useAutoTradeEngine";
import { useTradingAccounts } from "@/hooks/useTradingPreview";

const MODE_LABEL: Record<AutoTradeMode, string> = {
  OFF: "OFF",
  PAPER_ONLY: "Paper only",
  LIVE_MANUAL_CONFIRM: "Manual confirmation required",
  LIVE_AUTO: "Live auto",
};

export default function AutoTradePage() {
  const accounts = useTradingAccounts();
  const [accountId, setAccountId] = useState<string>("");
  const selected = useMemo(
    () => accountId || accounts.data[0]?.id || "",
    [accountId, accounts.data],
  );

  const settings = useAutoTradeSettings(selected || null);
  const state = useAutoTradeState(selected || null);
  const audit = useAutoTradeAuditLogs(selected || null);
  const actions = useAutoTradeActions(selected || null);
  const reauth = useAutoTradeReauth(selected || null);

  // Modal state.
  const [reauthOpen, setReauthOpen] = useState(false);
  const [reauthEmail, setReauthEmail] = useState("");
  const [reauthPassword, setReauthPassword] = useState("");
  const [reauthError, setReauthError] = useState<string | null>(null);
  const [riskAckOpen, setRiskAckOpen] = useState(false);
  const [riskAckChecked, setRiskAckChecked] = useState(false);
  const [stopOpen, setStopOpen] = useState(false);
  const [stopReason, setStopReason] = useState("user_initiated");

  // Risk limits form local state — synced with settings on load.
  const [form, setForm] = useState({
    max_capital_vnd: "",
    max_order_value_vnd: "",
    max_orders_per_day: "",
    max_daily_loss_vnd: "",
    max_position_weight: "",
    max_sector_weight: "",
    allowed_strategies: "",
    allowed_symbols: "",
  });

  // Push backend values into form when settings load.
  const settingsLoaded = settings.data?.account_id;
  useMemo(() => {
    if (!settings.data) return;
    setForm({
      max_capital_vnd: String(settings.data.max_capital_vnd || ""),
      max_order_value_vnd: String(settings.data.max_order_value_vnd || ""),
      max_orders_per_day: String(settings.data.max_orders_per_day || ""),
      max_daily_loss_vnd: String(settings.data.max_daily_loss_vnd || ""),
      max_position_weight: String(settings.data.max_position_weight || ""),
      max_sector_weight: String(settings.data.max_sector_weight || ""),
      allowed_strategies: settings.data.allowed_strategies.join(","),
      allowed_symbols: settings.data.allowed_symbols.join(","),
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [settingsLoaded]);

  async function onSaveLimits(e: React.FormEvent) {
    e.preventDefault();
    if (!selected) return;
    await settings.save({
      max_capital_vnd: Number(form.max_capital_vnd) || 0,
      max_order_value_vnd: Number(form.max_order_value_vnd) || 0,
      max_orders_per_day: Number(form.max_orders_per_day) || 0,
      max_daily_loss_vnd: Number(form.max_daily_loss_vnd) || 0,
      max_position_weight: Number(form.max_position_weight) || 0,
      max_sector_weight: Number(form.max_sector_weight) || 0,
      allowed_strategies: form.allowed_strategies
        .split(",")
        .map((s) => s.trim())
        .filter(Boolean),
      allowed_symbols: form.allowed_symbols
        .split(",")
        .map((s) => s.trim().toUpperCase())
        .filter(Boolean),
    });
    await audit.refresh();
  }

  async function onEnablePaper() {
    const r = await actions.enablePaper();
    if (r?.validation_status === "VALID") {
      await Promise.all([settings.refresh(), state.refresh(), audit.refresh()]);
    }
  }

  async function onEnableManualConfirm() {
    const r = await actions.enableManualConfirm();
    if (r?.validation_status === "REJECTED") {
      // If REAUTH_REQUIRED is in reasons, open the modal.
      if (r.rejection_reasons.some((x) => x.startsWith("REAUTH_REQUIRED"))) {
        setReauthOpen(true);
      }
    } else {
      await Promise.all([settings.refresh(), state.refresh(), audit.refresh()]);
    }
  }

  async function onRequestLiveAuto() {
    const r = await actions.requestLiveAuto();
    if (r?.validation_status === "REJECTED") {
      if (r.rejection_reasons.some((x) => x.startsWith("REAUTH_REQUIRED"))) {
        setReauthOpen(true);
        return;
      }
    } else if (r?.next_step === "CONFIRM_RISK_ACKNOWLEDGEMENT") {
      setRiskAckOpen(true);
    }
  }

  async function onConfirmLiveAuto() {
    const r = await actions.confirmLiveAuto(riskAckChecked);
    if (r?.validation_status === "VALID") {
      setRiskAckOpen(false);
      setRiskAckChecked(false);
      await Promise.all([settings.refresh(), state.refresh(), audit.refresh()]);
    }
  }

  async function onDisable() {
    await actions.disable();
    await Promise.all([settings.refresh(), state.refresh(), audit.refresh()]);
  }

  async function onEmergencyStop() {
    const r = await actions.emergencyStop(stopReason);
    if (r?.validation_status === "VALID") {
      setStopOpen(false);
      await Promise.all([settings.refresh(), state.refresh(), audit.refresh()]);
    }
  }

  async function onReauthSubmit() {
    setReauthError(null);
    const r = await reauth.reauth(reauthEmail, reauthPassword);
    if (r.ok) {
      setReauthOpen(false);
      setReauthPassword("");
      await settings.refresh();
      await audit.refresh();
    } else {
      setReauthError(r.error);
    }
  }

  const currentMode: AutoTradeMode = settings.data?.mode ?? "OFF";
  const liveExecutionEnabled =
    actions.lastResult?.is_live_execution_enabled ?? false;

  return (
    <div className="space-y-6" data-testid="auto-trade-page">
      <header>
        <h1 className="text-xl font-semibold text-ink">Auto-trade</h1>
        <p className="text-sm text-ink-dim mt-1">
          Configure auto-trade modes and risk limits. No real orders are
          placed in this phase — execution stays disabled at the
          environment level.
        </p>
      </header>

      <div
        role="status"
        data-testid="phase-2-6-banner"
        className="rounded border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-xs text-amber-200"
      >
        <strong className="font-semibold">Research dashboard</strong> —
        auto trading can lose money. This is not a guaranteed-profit
        system; you must monitor recommendations and decisions yourself.
        Live execution is currently disabled.
      </div>

      {/* ── Account selector ─────────────────────────────────────── */}
      <Card title="Trading account" hint="Choose which account these settings apply to">
        {accounts.data.length === 0 ? (
          <p className="text-ink-muted text-xs">
            Register a trading account on the{" "}
            <a className="text-accent" href="/trading-preview">
              Trading Preview
            </a>{" "}
            page first.
          </p>
        ) : (
          <select
            data-testid="account-selector"
            value={selected}
            onChange={(e) => setAccountId(e.target.value)}
            className="rounded border border-border bg-bg px-2 py-1 text-xs text-ink"
          >
            {accounts.data.map((a) => (
              <option key={a.id} value={a.id}>
                {a.account_alias ?? a.account_number_masked} ({a.broker})
              </option>
            ))}
          </select>
        )}
      </Card>

      {selected ? (
        <>
          {/* ── Current Mode Card ─────────────────────────────── */}
          <Card
            title="Current mode"
            hint={`Live execution: ${liveExecutionEnabled ? "ENABLED" : "DISABLED"}`}
          >
            <div className="flex items-center gap-3 flex-wrap">
              <Badge
                tone={
                  currentMode === "OFF"
                    ? "neutral"
                    : currentMode === "LIVE_AUTO"
                      ? "down"
                      : "info"
                }
              >
                <span data-testid="current-mode">{MODE_LABEL[currentMode]}</span>
              </Badge>
              {state.data?.is_running ? (
                <Badge tone="up">Running</Badge>
              ) : (
                <Badge tone="neutral">Idle</Badge>
              )}
              {state.data?.emergency_stopped_at ? (
                <Badge tone="down">Emergency stopped</Badge>
              ) : null}
            </div>
            {actions.error ? (
              <p
                data-testid="actions-error"
                className="text-accent-down text-xs mt-2"
              >
                {actions.error}
              </p>
            ) : null}
          </Card>

          {/* ── Mode selector ─────────────────────────────────── */}
          <Card title="Enable mode" hint="OFF is always allowed">
            <div className="flex gap-2 flex-wrap text-xs">
              <button
                data-testid="btn-off"
                type="button"
                onClick={onDisable}
                disabled={actions.busy}
                className="rounded border border-border bg-bg-panel px-3 py-1 text-ink hover:bg-bg disabled:opacity-50"
              >
                OFF
              </button>
              <button
                data-testid="btn-paper"
                type="button"
                onClick={onEnablePaper}
                disabled={actions.busy}
                className="rounded border border-border bg-bg-panel px-3 py-1 text-ink hover:bg-bg disabled:opacity-50"
              >
                Paper only
              </button>
              <button
                data-testid="btn-manual-confirm"
                type="button"
                onClick={onEnableManualConfirm}
                disabled={actions.busy}
                className="rounded border border-amber-500/60 bg-amber-500/10 px-3 py-1 text-amber-200 hover:bg-amber-500/20 disabled:opacity-50"
              >
                Manual confirmation required
              </button>
              <button
                data-testid="btn-live-auto"
                type="button"
                onClick={onRequestLiveAuto}
                disabled={actions.busy}
                className="rounded border border-accent-down/60 bg-accent-down/10 px-3 py-1 text-accent-down hover:bg-accent-down/20 disabled:opacity-50"
              >
                Live auto locked
              </button>
            </div>
            {actions.lastResult?.validation_status === "REJECTED" ? (
              <div
                data-testid="rejection-list"
                className="mt-3 rounded border border-accent-down/40 bg-accent-down/10 px-3 py-2 text-xs"
              >
                <strong className="text-accent-down">Cannot enable:</strong>
                <ul className="list-disc list-inside text-accent-down mt-1 space-y-0.5">
                  {actions.lastResult.rejection_reasons.map((r, i) => (
                    <li key={i}>{r}</li>
                  ))}
                </ul>
              </div>
            ) : null}
          </Card>

          {/* ── Risk limits form ──────────────────────────────── */}
          <Card title="Risk limits" hint="Required for Live auto">
            <form
              data-testid="risk-limits-form"
              onSubmit={onSaveLimits}
              className="grid grid-cols-2 lg:grid-cols-3 gap-3 text-xs"
            >
              <Field
                label="Max capital (VND)"
                testid="input-max-capital"
                value={form.max_capital_vnd}
                onChange={(v) => setForm({ ...form, max_capital_vnd: v })}
              />
              <Field
                label="Max order value (VND)"
                testid="input-max-order-value"
                value={form.max_order_value_vnd}
                onChange={(v) =>
                  setForm({ ...form, max_order_value_vnd: v })
                }
              />
              <Field
                label="Max orders per day"
                testid="input-max-orders"
                value={form.max_orders_per_day}
                onChange={(v) =>
                  setForm({ ...form, max_orders_per_day: v })
                }
              />
              <Field
                label="Max daily loss (VND)"
                testid="input-max-loss"
                value={form.max_daily_loss_vnd}
                onChange={(v) =>
                  setForm({ ...form, max_daily_loss_vnd: v })
                }
              />
              <Field
                label="Max position weight (0–1)"
                testid="input-max-position"
                value={form.max_position_weight}
                onChange={(v) =>
                  setForm({ ...form, max_position_weight: v })
                }
              />
              <Field
                label="Max sector weight (0–1)"
                testid="input-max-sector"
                value={form.max_sector_weight}
                onChange={(v) =>
                  setForm({ ...form, max_sector_weight: v })
                }
              />
              <label className="col-span-2 lg:col-span-3 flex flex-col gap-1">
                <span className="text-ink-dim">
                  Allowed strategies (comma-separated)
                </span>
                <input
                  data-testid="input-strategies"
                  value={form.allowed_strategies}
                  onChange={(e) =>
                    setForm({ ...form, allowed_strategies: e.target.value })
                  }
                  className="rounded border border-border bg-bg px-2 py-1 text-ink"
                />
              </label>
              <label className="col-span-2 lg:col-span-3 flex flex-col gap-1">
                <span className="text-ink-dim">
                  Allowed symbols (comma-separated)
                </span>
                <input
                  data-testid="input-symbols"
                  value={form.allowed_symbols}
                  onChange={(e) =>
                    setForm({ ...form, allowed_symbols: e.target.value })
                  }
                  className="rounded border border-border bg-bg px-2 py-1 text-ink"
                />
              </label>
              <div className="col-span-2 lg:col-span-3">
                <button
                  data-testid="save-limits"
                  type="submit"
                  className="rounded border border-accent/60 bg-accent/10 px-3 py-1 text-xs text-accent hover:bg-accent/20"
                >
                  Save limits
                </button>
              </div>
            </form>
          </Card>

          {/* ── Emergency stop ────────────────────────────────── */}
          {currentMode !== "OFF" ? (
            <Card title="Emergency stop" hint="Hard kill switch">
              <button
                data-testid="btn-emergency-stop"
                type="button"
                onClick={() => setStopOpen(true)}
                className="rounded border border-accent-down bg-accent-down/15 px-3 py-1.5 text-xs text-accent-down hover:bg-accent-down/25 font-semibold"
              >
                Emergency stop
              </button>
            </Card>
          ) : null}

          {/* ── Audit log ─────────────────────────────────────── */}
          <Card title="Audit log" hint="Recent auto-trade actions">
            {audit.data.length === 0 ? (
              <p className="text-ink-muted text-xs">No events yet.</p>
            ) : (
              <table data-testid="audit-log-table" className="w-full text-xs">
                <thead className="text-ink-dim">
                  <tr>
                    <th className="text-left">When</th>
                    <th className="text-left">Action</th>
                  </tr>
                </thead>
                <tbody>
                  {audit.data.slice(0, 20).map((row) => (
                    <tr key={row.id} className="text-ink">
                      <td className="font-mono">
                        {new Date(row.created_at).toLocaleString()}
                      </td>
                      <td>{row.action}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </Card>

          <Phase29EngineSection accountId={selected} />
        </>
      ) : null}

      {/* ── Re-auth modal ─────────────────────────────────────── */}
      {reauthOpen ? (
        <Modal title="Re-authenticate" onClose={() => setReauthOpen(false)}>
          <p className="text-xs text-ink-dim mb-3">
            Please re-enter your password to enable a live mode. Your
            password is sent only to Supabase — the dashboard never sees
            or stores it.
          </p>
          <input
            data-testid="reauth-email"
            type="email"
            placeholder="email"
            value={reauthEmail}
            onChange={(e) => setReauthEmail(e.target.value)}
            className="w-full rounded border border-border bg-bg px-2 py-1 text-xs text-ink mb-2"
          />
          <input
            data-testid="reauth-password"
            type="password"
            placeholder="password"
            value={reauthPassword}
            onChange={(e) => setReauthPassword(e.target.value)}
            className="w-full rounded border border-border bg-bg px-2 py-1 text-xs text-ink mb-3"
          />
          {reauthError ? (
            <p
              data-testid="reauth-error"
              className="text-accent-down text-xs mb-2"
            >
              {reauthError}
            </p>
          ) : null}
          <div className="flex gap-2">
            <button
              data-testid="reauth-submit"
              type="button"
              onClick={onReauthSubmit}
              className="rounded border border-accent/60 bg-accent/10 px-3 py-1 text-xs text-accent"
            >
              Re-authenticate
            </button>
            <button
              type="button"
              onClick={() => setReauthOpen(false)}
              className="rounded border border-border bg-bg-panel px-3 py-1 text-xs text-ink"
            >
              Cancel
            </button>
          </div>
        </Modal>
      ) : null}

      {/* ── Risk acknowledgement modal ─────────────────────────── */}
      {riskAckOpen ? (
        <Modal
          title="Risk acknowledgement"
          onClose={() => setRiskAckOpen(false)}
        >
          <p className="text-xs text-accent-down mb-3 font-semibold">
            Auto trading can lose money. This is a research system, not a
            guaranteed-profit signal. You must monitor your account
            yourself.
          </p>
          <label className="flex items-center gap-2 text-xs text-ink mb-3">
            <input
              data-testid="risk-ack-checkbox"
              type="checkbox"
              checked={riskAckChecked}
              onChange={(e) => setRiskAckChecked(e.target.checked)}
            />
            I acknowledge the risk and confirm I will monitor my account.
          </label>
          <div className="flex gap-2">
            <button
              data-testid="risk-ack-confirm"
              type="button"
              disabled={!riskAckChecked}
              onClick={onConfirmLiveAuto}
              className="rounded border border-accent-down/60 bg-accent-down/10 px-3 py-1 text-xs text-accent-down disabled:opacity-50"
            >
              Confirm Live auto
            </button>
            <button
              type="button"
              onClick={() => setRiskAckOpen(false)}
              className="rounded border border-border bg-bg-panel px-3 py-1 text-xs text-ink"
            >
              Cancel
            </button>
          </div>
        </Modal>
      ) : null}

      {/* ── Emergency stop modal ──────────────────────────────── */}
      {stopOpen ? (
        <Modal title="Emergency stop" onClose={() => setStopOpen(false)}>
          <p className="text-xs text-accent-down mb-3 font-semibold">
            This will set the mode to OFF and disable any running
            auto-trade flag for this account.
          </p>
          <input
            value={stopReason}
            onChange={(e) => setStopReason(e.target.value)}
            placeholder="Reason"
            className="w-full rounded border border-border bg-bg px-2 py-1 text-xs text-ink mb-3"
          />
          <div className="flex gap-2">
            <button
              data-testid="stop-confirm"
              type="button"
              onClick={onEmergencyStop}
              className="rounded border border-accent-down bg-accent-down/15 px-3 py-1 text-xs text-accent-down font-semibold"
            >
              Stop now
            </button>
            <button
              type="button"
              onClick={() => setStopOpen(false)}
              className="rounded border border-border bg-bg-panel px-3 py-1 text-xs text-ink"
            >
              Cancel
            </button>
          </div>
        </Modal>
      ) : null}
    </div>
  );
}

function Field({
  label,
  testid,
  value,
  onChange,
}: {
  label: string;
  testid: string;
  value: string;
  onChange: (v: string) => void;
}) {
  return (
    <label className="flex flex-col gap-1">
      <span className="text-ink-dim">{label}</span>
      <input
        data-testid={testid}
        type="number"
        min={0}
        step="any"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="rounded border border-border bg-bg px-2 py-1 text-ink"
      />
    </label>
  );
}

function Modal({
  title,
  children,
  onClose,
}: {
  title: string;
  children: React.ReactNode;
  onClose: () => void;
}) {
  return (
    <div
      role="dialog"
      aria-label={title}
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60"
      onClick={onClose}
    >
      <div
        className="w-full max-w-md rounded-lg border border-border bg-bg-panel p-4"
        onClick={(e) => e.stopPropagation()}
      >
        <h2 className="text-sm font-semibold text-ink mb-3">{title}</h2>
        {children}
      </div>
    </div>
  );
}

function Phase29EngineSection({ accountId }: { accountId: string }) {
  const runs = useAutoTradeRuns(accountId || null);
  const counters = useAutoTradeRiskCounters(accountId || null);
  const activeRun = runs.data.find(
    (r) => r.status === "RUNNING" || r.status === "PAUSED" || r.status === "STARTED",
  );
  const decisions = useAutoTradeDecisions(activeRun?.id ?? null, null);
  const engineOrders = useAutoTradeEngineOrders(activeRun?.id ?? null, null);
  const runActions = useAutoTradeRunActions(accountId || null);

  async function onStart() {
    const row = await runActions.startRun();
    if (row) await runs.refresh();
  }

  async function onStop() {
    if (!activeRun) return;
    await runActions.stopRun(activeRun.id);
    await runs.refresh();
  }

  async function onPause() {
    if (!activeRun) return;
    await runActions.pauseRun(activeRun.id);
    await runs.refresh();
  }

  const todayCounter = counters.data[0]; // newest first
  const dispatchedToday = engineOrders.data.length;

  return (
    <div className="space-y-4">
      <Card title="Phase 2.9 — Guarded auto trading" hint="High risk">
        <div
          role="alert"
          data-testid="phase-2-9-engine-warning"
          className="rounded border border-accent-down/40 bg-accent-down/10 px-3 py-2 text-xs text-accent-down mb-3"
        >
          <strong className="font-semibold">⚠ High risk.</strong> Live auto
          can lose money fast. You must monitor your account. This is a
          research system — not financial advice, not a guaranteed-profit
          signal.
        </div>
        <div className="flex gap-2 items-center flex-wrap">
          <span data-testid="engine-run-status">
            <Badge
              tone={
                activeRun?.status === "RUNNING"
                  ? "up"
                  : activeRun?.status === "PAUSED"
                    ? "neutral"
                    : "neutral"
              }
            >
              {activeRun?.status ?? "NO RUN"}
            </Badge>
          </span>
          {activeRun ? (
            <span className="text-xs text-ink">
              run {activeRun.id.slice(0, 8)}…
            </span>
          ) : null}
        </div>
        <div className="mt-3 flex gap-2 flex-wrap text-xs">
          <button
            data-testid="engine-start"
            type="button"
            onClick={onStart}
            disabled={runActions.busy || !!activeRun}
            className="rounded border border-border bg-bg-panel px-3 py-1 text-ink disabled:opacity-50"
          >
            Start run
          </button>
          <button
            data-testid="engine-pause"
            type="button"
            onClick={onPause}
            disabled={!activeRun || activeRun.status !== "RUNNING"}
            className="rounded border border-amber-500/60 bg-amber-500/10 px-3 py-1 text-amber-200 disabled:opacity-50"
          >
            Pause
          </button>
          <button
            data-testid="engine-stop"
            type="button"
            onClick={onStop}
            disabled={!activeRun}
            className="rounded border border-accent-down/60 bg-accent-down/10 px-3 py-1 text-accent-down disabled:opacity-50"
          >
            Stop
          </button>
        </div>
        {runActions.error ? (
          <p
            data-testid="engine-error"
            className="mt-2 text-accent-down text-xs"
          >
            {runActions.error}
          </p>
        ) : null}
      </Card>

      <Card title="Today's risk counters">
        {todayCounter ? (
          <dl
            data-testid="risk-counters"
            className="grid grid-cols-2 gap-2 text-xs"
          >
            <dt className="text-ink-dim">Orders today</dt>
            <dd className="text-right text-ink">
              {todayCounter.orders_count}
            </dd>
            <dt className="text-ink-dim">Gross order value</dt>
            <dd className="text-right text-ink">
              {formatVnd(todayCounter.gross_order_value)}
            </dd>
          </dl>
        ) : (
          <p className="text-ink-muted text-xs">No orders today.</p>
        )}
      </Card>

      <Card title="Recent engine decisions">
        {decisions.data.length === 0 ? (
          <p className="text-ink-muted text-xs">No decisions yet.</p>
        ) : (
          <table data-testid="engine-decisions" className="w-full text-xs">
            <thead className="text-ink-dim">
              <tr>
                <th>When</th>
                <th>Symbol</th>
                <th>Action</th>
                <th>Outcome</th>
              </tr>
            </thead>
            <tbody>
              {decisions.data.slice(0, 15).map((d) => (
                <tr key={d.id} className="text-ink">
                  <td className="font-mono">{d.created_at.slice(0, 16)}</td>
                  <td>{d.symbol}</td>
                  <td>{d.action}</td>
                  <td
                    className={
                      d.decision.startsWith("DISPATCHED")
                        ? "text-accent"
                        : "text-amber-200"
                    }
                  >
                    {d.decision}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>
    </div>
  );
}
