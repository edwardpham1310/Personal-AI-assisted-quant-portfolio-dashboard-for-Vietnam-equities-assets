"use client";

import { useState } from "react";
import { Card } from "@/components/ui/Card";
import { Badge } from "@/components/ui/Badge";
import { EmptyState } from "@/components/ui/AsyncStates";
import { Skeleton } from "@/components/ui/Skeleton";
import { useAlerts, type AlertCondition, type AlertWithStatus } from "@/hooks/useAlerts";
import { formatPct } from "@/lib/format";

const CONDITIONS: { value: AlertCondition; label: string; pct: boolean }[] = [
  { value: "price_above", label: "Price ≥", pct: false },
  { value: "price_below", label: "Price ≤", pct: false },
  { value: "pct_change_above", label: "Day change ≥", pct: true },
  { value: "pct_change_below", label: "Day change ≤", pct: true },
];

function condMeta(c: AlertCondition) {
  return CONDITIONS.find((x) => x.value === c) ?? CONDITIONS[0];
}

function thresholdLabel(a: AlertWithStatus): string {
  const meta = condMeta(a.condition);
  return meta.pct ? formatPct(a.threshold) : a.threshold.toLocaleString();
}

function observedLabel(a: AlertWithStatus): string {
  if (!a.evaluated) return "—";
  const meta = condMeta(a.condition);
  if (meta.pct) return a.observed_change_pct != null ? formatPct(a.observed_change_pct) : "—";
  return a.observed_price != null ? a.observed_price.toLocaleString() : "—";
}

/**
 * Alert management — create / list / toggle / delete research notification
 * rules (price or day-change thresholds). Evaluated server-side against the
 * latest cached quote; alerts never place an order. Honest-empty states.
 */
export function AlertsPanel() {
  const { data, loading, error, refresh, create, update, remove } = useAlerts();
  const [symbol, setSymbol] = useState("");
  const [condition, setCondition] = useState<AlertCondition>("price_above");
  const [threshold, setThreshold] = useState("");
  const [busy, setBusy] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

  const alerts = data?.alerts ?? [];
  const isPct = condMeta(condition).pct;

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    const sym = symbol.trim().toUpperCase();
    const raw = Number(threshold);
    if (!sym || !Number.isFinite(raw)) {
      setFormError("Enter a symbol and a numeric threshold.");
      return;
    }
    setBusy(true);
    setFormError(null);
    try {
      // pct conditions are stored as a fraction (user types 3 → 0.03).
      const value = isPct ? raw / 100 : raw;
      await create({ symbol: sym, condition, threshold: value });
      setSymbol("");
      setThreshold("");
      await refresh();
    } catch (err) {
      setFormError(err instanceof Error ? err.message : "Could not create alert.");
    } finally {
      setBusy(false);
    }
  }

  async function toggle(a: AlertWithStatus) {
    await update(a.id, { is_active: !a.is_active });
    await refresh();
  }

  async function del(a: AlertWithStatus) {
    await remove(a.id);
    await refresh();
  }

  return (
    <Card
      title="Alerts"
      hint="Research notifications · price / day-change thresholds · no orders placed"
    >
      <form onSubmit={submit} className="mb-4 flex flex-wrap items-center gap-2">
        <input
          value={symbol}
          onChange={(e) => setSymbol(e.target.value)}
          placeholder="Symbol"
          aria-label="Alert symbol"
          className="w-28 rounded border border-border bg-bg px-2 py-1 text-sm uppercase text-ink"
        />
        <select
          value={condition}
          onChange={(e) => setCondition(e.target.value as AlertCondition)}
          aria-label="Alert condition"
          className="rounded border border-border bg-bg px-2 py-1 text-sm text-ink"
        >
          {CONDITIONS.map((c) => (
            <option key={c.value} value={c.value}>
              {c.label}
            </option>
          ))}
        </select>
        <input
          value={threshold}
          onChange={(e) => setThreshold(e.target.value)}
          placeholder={isPct ? "%" : "price"}
          inputMode="decimal"
          aria-label="Alert threshold"
          className="w-24 rounded border border-border bg-bg px-2 py-1 text-sm text-ink"
        />
        <button
          type="submit"
          disabled={busy}
          className="rounded border border-border bg-bg-subtle px-3 py-1 text-sm text-ink hover:border-accent disabled:opacity-50"
        >
          Add alert
        </button>
      </form>
      {formError ? <p className="mb-3 text-xs text-accent-down">{formError}</p> : null}

      {loading && alerts.length === 0 ? (
        <Skeleton height={120} />
      ) : error ? (
        <p className="text-xs text-accent-down">{error}</p>
      ) : alerts.length === 0 ? (
        <EmptyState>No alerts yet. Add one above to watch a symbol.</EmptyState>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead className="text-ink-dim">
              <tr className="text-left">
                <th className="py-1">Symbol</th>
                <th className="py-1">Condition</th>
                <th className="py-1 text-right">Threshold</th>
                <th className="py-1 text-right">Observed</th>
                <th className="py-1">Status</th>
                <th className="py-1" />
                <th className="py-1" />
              </tr>
            </thead>
            <tbody className="font-mono text-ink-muted">
              {alerts.map((a) => (
                <tr key={a.id} className="border-t border-border">
                  <td className="py-1 text-ink">{a.symbol}</td>
                  <td className="py-1 font-sans">{condMeta(a.condition).label}</td>
                  <td className="py-1 text-right">{thresholdLabel(a)}</td>
                  <td className="py-1 text-right">
                    {observedLabel(a)}
                    {a.quote_stale ? <span className="ml-1 text-[10px] text-ink-dim">stale</span> : null}
                  </td>
                  <td className="py-1">
                    {!a.is_active ? (
                      <Badge tone="neutral">Paused</Badge>
                    ) : !a.evaluated ? (
                      <Badge tone="neutral">No quote</Badge>
                    ) : a.currently_triggered ? (
                      <Badge tone="up">Triggered</Badge>
                    ) : (
                      <Badge tone="neutral">Waiting</Badge>
                    )}
                  </td>
                  <td className="py-1 text-right">
                    <button
                      type="button"
                      onClick={() => void toggle(a)}
                      className="text-[11px] text-ink-muted hover:text-accent"
                    >
                      {a.is_active ? "Pause" : "Resume"}
                    </button>
                  </td>
                  <td className="py-1 text-right">
                    <button
                      type="button"
                      onClick={() => void del(a)}
                      className="text-[11px] text-ink-muted hover:text-accent-down"
                    >
                      Delete
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}
