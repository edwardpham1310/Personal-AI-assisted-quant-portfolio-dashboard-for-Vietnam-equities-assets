"use client";

import { useMemo, useState } from "react";
import { Card } from "@/components/ui/Card";
import { Badge } from "@/components/ui/Badge";
import { formatVnd } from "@/lib/format";
import {
  useLiveOrderActions,
  useLiveOrderIntents,
  type LiveOrderIntent,
  type LiveOrderIntentResult,
  type OrderType,
  type Side,
} from "@/hooks/useLiveOrderIntents";
import { useTradingAccounts } from "@/hooks/useTradingPreview";
import { useAutoTradeReauth } from "@/hooks/useAutoTrade";

const SIDES: Side[] = ["BUY", "SELL"];
const ORDER_TYPES: OrderType[] = ["LIMIT", "MARKET"];

export default function ManualConfirmPage() {
  const accounts = useTradingAccounts();
  const [accountId, setAccountId] = useState<string>("");
  const selected = useMemo(
    () => accountId || accounts.data[0]?.id || "",
    [accountId, accounts.data],
  );

  const intents = useLiveOrderIntents(selected || null);
  const actions = useLiveOrderActions(selected || null);
  const reauth = useAutoTradeReauth(selected || null);

  // Form state for the create-intent step.
  const [symbol, setSymbol] = useState("FPT");
  const [side, setSide] = useState<Side>("BUY");
  const [orderType, setOrderType] = useState<OrderType>("LIMIT");
  const [quantity, setQuantity] = useState(100);
  const [limitPrice, setLimitPrice] = useState("86000");

  const [activeIntent, setActiveIntent] = useState<LiveOrderIntent | null>(
    null,
  );
  const [reauthOpen, setReauthOpen] = useState(false);
  const [reauthEmail, setReauthEmail] = useState("");
  const [reauthPassword, setReauthPassword] = useState("");
  const [reauthError, setReauthError] = useState<string | null>(null);
  const [riskAckOpen, setRiskAckOpen] = useState(false);
  const [riskAckChecked, setRiskAckChecked] = useState(false);
  const [submitOpen, setSubmitOpen] = useState(false);

  async function onCreate(e: React.FormEvent) {
    e.preventDefault();
    if (!selected) return;
    const lp = limitPrice ? Number(limitPrice) : null;
    const row = await actions.create({
      symbol: symbol.toUpperCase(),
      side,
      order_type: orderType,
      quantity,
      limit_price: lp,
    });
    if (row) {
      setActiveIntent(row);
      await intents.refresh();
    }
  }

  async function onPreview() {
    if (!activeIntent) return;
    const r = await actions.preview(activeIntent.id);
    if (r) {
      setActiveIntent(r.intent);
      await intents.refresh();
    }
  }

  async function onRequestConfirmation() {
    if (!activeIntent) return;
    const r = await actions.requestConfirmation(activeIntent.id);
    if (r) {
      setActiveIntent(r.intent);
      // Open the re-auth modal so the user can refresh their password.
      setReauthOpen(true);
    }
  }

  async function onReauthSubmit() {
    setReauthError(null);
    const r = await reauth.reauth(reauthEmail, reauthPassword);
    if (r.ok) {
      setReauthOpen(false);
      setReauthPassword("");
      setRiskAckOpen(true);
    } else {
      setReauthError(r.error);
    }
  }

  async function onConfirmIntent() {
    if (!activeIntent) return;
    const r = await actions.confirm(activeIntent.id, riskAckChecked);
    if (r) {
      setActiveIntent(r.intent);
      setRiskAckOpen(false);
      setRiskAckChecked(false);
      if (r.intent.status === "CONFIRMED") setSubmitOpen(true);
    }
  }

  async function onFinalSubmit() {
    if (!activeIntent) return;
    const r = await actions.submit(activeIntent.id);
    if (r) {
      setActiveIntent(r.intent);
      setSubmitOpen(false);
      await intents.refresh();
    }
  }

  async function onCancel() {
    if (!activeIntent) return;
    await actions.cancel(activeIntent.id);
    setActiveIntent(null);
    await intents.refresh();
  }

  const result = actions.lastResult;
  const gate = result?.gate_status;
  const dryRun = result?.is_dry_run ?? true;

  return (
    <div className="space-y-6" data-testid="manual-confirm-page">
      <header>
        <h1 className="text-xl font-semibold text-ink">
          Manual confirm live order
        </h1>
        <p className="text-sm text-ink-dim mt-1">
          Step-by-step gated submission. No one-click trade. No hidden
          submit. No background path.
        </p>
      </header>

      {/* Mode banner — DRY RUN by default, strong warning if live */}
      {gate?.all_open && !dryRun ? (
        <div
          role="alert"
          data-testid="live-warning-banner"
          className="rounded border border-accent-down/60 bg-accent-down/10 px-3 py-2 text-xs text-accent-down font-semibold"
        >
          ⚠ This will submit a REAL order to SSI. The submit button below
          is the last chance to cancel.
        </div>
      ) : (
        <div
          role="status"
          data-testid="dry-run-banner"
          className="rounded border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-xs text-amber-200"
        >
          DRY RUN — no real order will be submitted. To enable live
          submission, all 5 environment flags must align (currently
          {gate
            ? ` ${Object.values(gate).filter(Boolean).length}/5`
            : ""}{" "}
          open).
        </div>
      )}

      {/* Account selector */}
      <Card title="Trading account">
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
      </Card>

      {/* Step 1 — create intent */}
      <Card
        title="Step 1 — create intent"
        hint="Define the order. Nothing is sent yet."
      >
        <form
          onSubmit={onCreate}
          data-testid="create-intent-form"
          className="grid grid-cols-2 lg:grid-cols-5 gap-3 text-xs"
        >
          <Field
            label="Symbol"
            testid="loi-symbol"
            value={symbol}
            onChange={(v) => setSymbol(v.toUpperCase())}
          />
          <SelectField
            label="Side"
            testid="loi-side"
            value={side}
            options={SIDES}
            onChange={(v) => setSide(v as Side)}
          />
          <SelectField
            label="Order type"
            testid="loi-order-type"
            value={orderType}
            options={ORDER_TYPES}
            onChange={(v) => setOrderType(v as OrderType)}
          />
          <NumberField
            label="Quantity"
            testid="loi-quantity"
            value={quantity}
            onChange={setQuantity}
          />
          <Field
            label="Limit price (VND)"
            testid="loi-limit"
            value={limitPrice}
            onChange={setLimitPrice}
          />
          <div className="col-span-2 lg:col-span-5">
            <button
              data-testid="loi-create"
              type="submit"
              disabled={actions.busy}
              className="rounded border border-border bg-bg-panel px-3 py-1 text-ink disabled:opacity-50"
            >
              {actions.busy ? "…" : "Create intent"}
            </button>
          </div>
        </form>
      </Card>

      {/* Active intent steps */}
      {activeIntent ? (
        <Card
          title="Active intent"
          hint={`Status: ${activeIntent.status}`}
        >
          <div className="flex items-center gap-3 flex-wrap text-xs">
            <Badge tone="info">{activeIntent.symbol}</Badge>
            <Badge tone="neutral">{activeIntent.side}</Badge>
            <span className="text-ink">
              qty {activeIntent.quantity}
              {activeIntent.limit_price
                ? ` @ ${formatVnd(activeIntent.limit_price)}`
                : ""}
            </span>
            <span data-testid="active-intent-status">
              <Badge
                tone={
                  activeIntent.status === "SUBMITTED"
                    ? "up"
                    : activeIntent.status === "REJECTED" ||
                        activeIntent.status === "FAILED"
                      ? "down"
                      : "info"
                }
              >
                {activeIntent.status}
              </Badge>
            </span>
          </div>

          <div className="mt-3 flex gap-2 flex-wrap text-xs">
            <button
              data-testid="step-preview"
              type="button"
              onClick={onPreview}
              disabled={
                actions.busy ||
                !["DRAFT", "PREVIEWED"].includes(activeIntent.status)
              }
              className="rounded border border-border bg-bg-panel px-3 py-1 text-ink disabled:opacity-50"
            >
              Step 2 — preview
            </button>
            <button
              data-testid="step-request-confirmation"
              type="button"
              onClick={onRequestConfirmation}
              disabled={
                actions.busy || activeIntent.status !== "PREVIEWED" ||
                activeIntent.rejection_reasons.length > 0
              }
              className="rounded border border-amber-500/60 bg-amber-500/10 px-3 py-1 text-amber-200 disabled:opacity-50"
            >
              Step 3 — request confirmation
            </button>
            <button
              data-testid="step-submit-open"
              type="button"
              onClick={() => setSubmitOpen(true)}
              disabled={activeIntent.status !== "CONFIRMED"}
              className="rounded border border-accent-down/60 bg-accent-down/10 px-3 py-1 text-accent-down disabled:opacity-50"
            >
              Step 5 — final submit
            </button>
            <button
              type="button"
              onClick={onCancel}
              disabled={[
                "SUBMITTED",
                "REJECTED",
                "CANCELLED",
                "FAILED",
              ].includes(activeIntent.status)}
              className="rounded border border-border bg-bg-panel px-3 py-1 text-ink disabled:opacity-50"
            >
              Cancel intent
            </button>
          </div>

          {result?.rejection_reasons?.length ? (
            <div
              data-testid="rejection-list"
              className="mt-3 rounded border border-accent-down/40 bg-accent-down/10 px-3 py-2"
            >
              <strong className="text-accent-down text-xs">
                Cannot proceed:
              </strong>
              <ul className="list-disc list-inside text-accent-down text-xs mt-1">
                {result.rejection_reasons.map((r, i) => (
                  <li key={i}>{r}</li>
                ))}
              </ul>
            </div>
          ) : null}
          {result?.warnings?.length ? (
            <div className="mt-2 text-xs text-amber-200">
              Warnings: {result.warnings.join(" · ")}
            </div>
          ) : null}
        </Card>
      ) : null}

      {/* Recent intents list */}
      <Card title="Recent intents">
        {intents.data.length === 0 ? (
          <p className="text-ink-muted text-xs">None yet.</p>
        ) : (
          <table data-testid="intents-table" className="w-full text-xs">
            <thead className="text-ink-dim">
              <tr>
                <th>Created</th>
                <th>Symbol</th>
                <th>Side</th>
                <th>Qty</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              {intents.data.slice(0, 15).map((i) => (
                <tr key={i.id} className="text-ink">
                  <td>{i.created_at?.slice(0, 16)}</td>
                  <td>{i.symbol}</td>
                  <td>{i.side}</td>
                  <td className="text-right">{i.quantity}</td>
                  <td>{i.status}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>

      {/* Re-auth modal (step 4a) */}
      {reauthOpen ? (
        <Modal title="Re-authenticate" onClose={() => setReauthOpen(false)}>
          <p className="text-xs text-ink-dim mb-3">
            Enter your password to confirm this live order. The password
            is sent only to Supabase — the dashboard never sees or
            stores it.
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
            <p className="text-accent-down text-xs mb-2">{reauthError}</p>
          ) : null}
          <button
            data-testid="reauth-submit"
            type="button"
            onClick={onReauthSubmit}
            className="rounded border border-accent/60 bg-accent/10 px-3 py-1 text-xs text-accent"
          >
            Re-authenticate
          </button>
        </Modal>
      ) : null}

      {/* Risk-ack modal (step 4b) */}
      {riskAckOpen ? (
        <Modal
          title="Risk acknowledgement"
          onClose={() => setRiskAckOpen(false)}
        >
          <p className="text-xs text-accent-down mb-3 font-semibold">
            You are about to submit a real-money order. Markets can move
            against you. You must monitor your account yourself.
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
          <button
            data-testid="risk-ack-confirm"
            type="button"
            disabled={!riskAckChecked}
            onClick={onConfirmIntent}
            className="rounded border border-accent-down/60 bg-accent-down/10 px-3 py-1 text-xs text-accent-down disabled:opacity-50"
          >
            Confirm
          </button>
        </Modal>
      ) : null}

      {/* Final submit modal (step 5) — only after CONFIRMED */}
      {submitOpen && activeIntent?.status === "CONFIRMED" ? (
        <Modal
          title="Final submit"
          onClose={() => setSubmitOpen(false)}
        >
          <p className="text-xs text-ink mb-3">
            {dryRun ? (
              <span data-testid="modal-dry-run-label">
                DRY RUN — clicking will simulate a broker submission. No
                real order will be sent.
              </span>
            ) : (
              <span
                data-testid="modal-live-warning"
                className="text-accent-down font-semibold"
              >
                LIVE SUBMISSION — clicking will send a real order to SSI.
              </span>
            )}
          </p>
          <dl className="grid grid-cols-2 gap-1 text-xs mb-3">
            <dt className="text-ink-dim">Symbol</dt>
            <dd className="text-right text-ink">{activeIntent.symbol}</dd>
            <dt className="text-ink-dim">Side</dt>
            <dd className="text-right text-ink">{activeIntent.side}</dd>
            <dt className="text-ink-dim">Quantity</dt>
            <dd className="text-right text-ink">{activeIntent.quantity}</dd>
            <dt className="text-ink-dim">Limit price</dt>
            <dd className="text-right text-ink">
              {activeIntent.limit_price
                ? formatVnd(activeIntent.limit_price)
                : "—"}
            </dd>
            <dt className="text-ink-dim">Account</dt>
            <dd className="text-right text-ink font-mono">
              {activeIntent.account_id.slice(0, 8)}…
            </dd>
          </dl>
          <button
            data-testid="final-submit"
            type="button"
            onClick={onFinalSubmit}
            className="rounded border border-accent-down bg-accent-down/15 px-3 py-1 text-xs text-accent-down font-semibold"
          >
            {dryRun ? "Submit (dry run)" : "Submit live order"}
          </button>
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
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="rounded border border-border bg-bg px-2 py-1 text-ink"
      />
    </label>
  );
}

function NumberField({
  label,
  testid,
  value,
  onChange,
}: {
  label: string;
  testid: string;
  value: number;
  onChange: (v: number) => void;
}) {
  return (
    <label className="flex flex-col gap-1">
      <span className="text-ink-dim">{label}</span>
      <input
        data-testid={testid}
        type="number"
        min={1}
        step={100}
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        className="rounded border border-border bg-bg px-2 py-1 text-ink"
      />
    </label>
  );
}

function SelectField({
  label,
  testid,
  value,
  options,
  onChange,
}: {
  label: string;
  testid: string;
  value: string;
  options: readonly string[];
  onChange: (v: string) => void;
}) {
  return (
    <label className="flex flex-col gap-1">
      <span className="text-ink-dim">{label}</span>
      <select
        data-testid={testid}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="rounded border border-border bg-bg px-2 py-1 text-ink"
      >
        {options.map((o) => (
          <option key={o} value={o}>
            {o}
          </option>
        ))}
      </select>
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
