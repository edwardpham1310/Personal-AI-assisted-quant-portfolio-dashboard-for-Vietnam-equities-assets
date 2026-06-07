"use client";

import { useState } from "react";
import { Card } from "@/components/ui/Card";
import { Badge } from "@/components/ui/Badge";
import { EmptyState } from "@/components/ui/AsyncStates";
import { Skeleton } from "@/components/ui/Skeleton";
import { RangeSelect } from "@/components/ui/RangeSelect";
import { EQUITY_RANGE_OPTIONS, type RangeKey } from "@/lib/dateRange";
import {
  useRecommendationHistory,
  useRecommendationPerformance,
  type RecommendationHistoryItem,
  type RecommendationSignal,
  type RecommendationStrength,
} from "@/hooks/useRecommendations";
import { formatPct } from "@/lib/format";

function strengthTone(s: RecommendationStrength): "up" | "down" | "neutral" {
  return s === "Strong" ? "up" : s === "Weak" ? "down" : "neutral";
}
function signalTone(s: RecommendationSignal): "up" | "down" | "neutral" | "info" {
  if (s === "Actionable" || s === "Accumulate") return "up";
  if (s === "Avoid" || s === "Risky") return "down";
  if (s === "Take Profit") return "info";
  return "neutral";
}

function shortDate(iso: string | null): string {
  if (!iso) return "—";
  return iso.slice(0, 10);
}

/**
 * Recommendation history + hypothetical performance. Both are RLS-scoped to the
 * user; history is sorted ascending by date (time-series rule). Performance is
 * a clearly-labelled hypothetical mark-to-market (reference price → latest
 * quote), never an executed-trade P&L. Honest-empty when there are no snapshots
 * or no prices.
 */
export function RecommendationHistorySection() {
  const [range, setRange] = useState<RangeKey>("3M");
  const history = useRecommendationHistory(range);
  const perf = useRecommendationPerformance(range);

  const items: RecommendationHistoryItem[] = history.data?.items ?? [];
  const p = perf.data;

  return (
    <Card
      title="History & performance"
      hint="Past signals · hypothetical mark-to-market, not executed trades"
      action={<RangeSelect value={range} options={EQUITY_RANGE_OPTIONS} onChange={setRange} />}
    >
      {/* Performance summary */}
      {perf.loading && !p ? (
        <Skeleton height={48} />
      ) : p && p.evaluated > 0 ? (
        <div className="mb-4 grid grid-cols-2 gap-3 sm:grid-cols-4">
          <Stat label="Evaluated" value={`${p.evaluated}/${p.total}`} />
          <Stat
            label="Win rate"
            value={p.win_rate != null ? `${Math.round(p.win_rate * 100)}%` : "—"}
          />
          <Stat
            label="Avg return"
            value={p.avg_return_pct != null ? formatPct(p.avg_return_pct) : "—"}
            tone={(p.avg_return_pct ?? 0) >= 0 ? "up" : "down"}
          />
          <Stat
            label="Best · Worst"
            value={
              p.best && p.worst
                ? `${formatPct(p.best.return_pct)} · ${formatPct(p.worst.return_pct)}`
                : "—"
            }
          />
        </div>
      ) : (
        <p className="mb-4 text-[11px] text-ink-dim">
          No hypothetical performance yet
          {p && p.total > 0
            ? ` (${p.skipped_no_reference} without a reference price, ${p.skipped_no_quote} without a current quote).`
            : " — signals are scored over time as you view symbols."}
        </p>
      )}

      {/* History table */}
      {history.loading && items.length === 0 ? (
        <Skeleton height={160} />
      ) : history.error ? (
        <p className="text-xs text-accent-down">{history.error}</p>
      ) : items.length === 0 ? (
        <EmptyState>No recommendation history in this range yet.</EmptyState>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead className="text-ink-dim">
              <tr className="text-left">
                <th className="py-1">Date</th>
                <th className="py-1">Symbol</th>
                <th className="py-1 text-right">Score</th>
                <th className="py-1">Strength</th>
                <th className="py-1">Signal</th>
                <th className="py-1 text-right">Ref. price</th>
                <th className="py-1 text-right">Conf.</th>
              </tr>
            </thead>
            <tbody className="font-mono text-ink-muted">
              {items.map((it) => (
                <tr key={it.id ?? `${it.symbol}-${it.created_at}`} className="border-t border-border">
                  <td className="py-1">{shortDate(it.created_at)}</td>
                  <td className="py-1 text-ink">{it.symbol}</td>
                  <td className="py-1 text-right text-ink">{it.final_score}</td>
                  <td className="py-1">
                    <Badge tone={strengthTone(it.strength)}>{it.strength}</Badge>
                  </td>
                  <td className="py-1">
                    <Badge tone={signalTone(it.signal)}>{it.signal}</Badge>
                  </td>
                  <td className="py-1 text-right">
                    {it.reference_price != null ? it.reference_price.toLocaleString() : "—"}
                  </td>
                  <td className="py-1 text-right">
                    {it.confidence != null ? `${Math.round(it.confidence * 100)}%` : "—"}
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

function Stat({
  label,
  value,
  tone,
}: {
  label: string;
  value: string;
  tone?: "up" | "down";
}) {
  const toneClass = tone === "up" ? "text-accent-up" : tone === "down" ? "text-accent-down" : "text-ink";
  return (
    <div className="rounded border border-border bg-bg-panel px-3 py-2">
      <div className="text-[10px] uppercase tracking-wide text-ink-dim">{label}</div>
      <div className={`text-sm font-medium ${toneClass}`}>{value}</div>
    </div>
  );
}
