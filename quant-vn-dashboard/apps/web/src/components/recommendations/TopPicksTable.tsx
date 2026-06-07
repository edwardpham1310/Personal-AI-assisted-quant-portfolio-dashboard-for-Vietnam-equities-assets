"use client";

import { useState } from "react";
import { Card } from "@/components/ui/Card";
import { Badge } from "@/components/ui/Badge";
import { EmptyState } from "@/components/ui/AsyncStates";
import { Skeleton } from "@/components/ui/Skeleton";
import { useTopPicks, type TopPick } from "@/hooks/useTopPicks";
import { formatNumber, formatPct, formatVnd } from "@/lib/format";

const STRATEGIES = [
  { value: "short_aggressive", label: "Short-term" },
  { value: "long_conservative", label: "Long-term" },
] as const;
const EXCHANGES = ["", "HOSE", "HNX", "UPCOM"];

function strengthTone(s: TopPick["strength"]): "up" | "down" | "neutral" {
  return s === "Strong" ? "up" : s === "Weak" ? "down" : "neutral";
}
function signalTone(s: TopPick["signal"]): "up" | "down" | "neutral" | "info" {
  if (s === "Actionable" || s === "Accumulate") return "up";
  if (s === "Avoid" || s === "Risky") return "down";
  if (s === "Take Profit") return "info";
  return "neutral";
}

/**
 * Top quant picks table (research signals — decision support, not advice).
 * Real data from /recommendations/top with honest empty/error states; never
 * shows mock picks. ``onAddToWatchlist`` is optional — wired in the Watchlist
 * feature; until then the action is disabled with a hint.
 */
export function TopPicksTable({
  onAddToWatchlist,
}: {
  onAddToWatchlist?: (symbol: string) => void;
}) {
  const [strategy, setStrategy] = useState<TopPicksStrategy>("short_aggressive");
  const [exchange, setExchange] = useState("");
  const { data, loading, error } = useTopPicks({ strategy, exchange: exchange || null });
  const picks = data?.picks ?? [];

  const filters = (
    <span className="inline-flex gap-2">
      <select
        aria-label="Strategy"
        value={strategy}
        onChange={(e) => setStrategy(e.target.value as TopPicksStrategy)}
        className="rounded border border-border bg-bg-panel px-2 py-0.5 text-xs text-ink-muted"
      >
        {STRATEGIES.map((s) => (
          <option key={s.value} value={s.value}>
            {s.label}
          </option>
        ))}
      </select>
      <select
        aria-label="Exchange"
        value={exchange}
        onChange={(e) => setExchange(e.target.value)}
        className="rounded border border-border bg-bg-panel px-2 py-0.5 text-xs text-ink-muted"
      >
        {EXCHANGES.map((x) => (
          <option key={x || "all"} value={x}>
            {x || "All exchanges"}
          </option>
        ))}
      </select>
    </span>
  );

  return (
    <Card
      title="Top quant picks"
      hint={`${data?.coverage === "full_market" ? "Full market" : "Tracked universe"} · research signals, not advice`}
      action={filters}
    >
      {loading && !data ? (
        <Skeleton height={220} />
      ) : error ? (
        <p className="text-xs text-accent-down">{error}</p>
      ) : picks.length === 0 ? (
        <EmptyState>No picks available right now (quote cache may be cold).</EmptyState>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead className="text-ink-dim">
              <tr className="text-left">
                <th className="py-1">Symbol</th>
                <th className="py-1 text-right">Price</th>
                <th className="py-1 text-right">Chg%</th>
                <th className="py-1 text-right">Volume</th>
                <th className="py-1 text-right">Value</th>
                <th className="py-1 text-right">Score</th>
                <th className="py-1">Strength</th>
                <th className="py-1">Signal</th>
                <th className="py-1 text-right">Conf.</th>
                <th className="py-1">Reason</th>
                <th className="py-1 text-right">＋</th>
              </tr>
            </thead>
            <tbody className="font-mono text-ink-muted">
              {picks.map((p) => (
                <tr key={p.symbol} className="border-t border-border align-top">
                  <td className="py-1 text-ink" title={p.company_name ?? undefined}>{p.symbol}</td>
                  <td className="py-1 text-right">{p.price != null ? formatNumber(p.price) : "—"}</td>
                  <td
                    className={`py-1 text-right ${
                      (p.change_pct ?? 0) > 0
                        ? "text-accent-up"
                        : (p.change_pct ?? 0) < 0
                          ? "text-accent-down"
                          : ""
                    }`}
                  >
                    {p.change_pct != null ? formatPct(p.change_pct) : "—"}
                  </td>
                  <td className="py-1 text-right">{p.volume != null ? formatNumber(p.volume) : "—"}</td>
                  <td className="py-1 text-right">
                    {p.value != null ? formatVnd(p.value, { compact: true }) : "—"}
                  </td>
                  <td className="py-1 text-right text-ink">{p.quant_score}</td>
                  <td className="py-1">
                    <Badge tone={strengthTone(p.strength)}>{p.strength}</Badge>
                  </td>
                  <td className="py-1">
                    <Badge tone={signalTone(p.signal)}>{p.signal}</Badge>
                  </td>
                  <td className="py-1 text-right">{Math.round(p.confidence * 100)}%</td>
                  <td className="py-1 max-w-[14rem] truncate font-sans text-ink-dim" title={p.reasons.join("; ")}>
                    {p.reasons[0] ?? "—"}
                  </td>
                  <td className="py-1 text-right">
                    <button
                      type="button"
                      onClick={() => onAddToWatchlist?.(p.symbol)}
                      disabled={!onAddToWatchlist}
                      title={onAddToWatchlist ? `Add ${p.symbol} to a watchlist` : "Manage on the Watchlist page"}
                      className="rounded border border-border px-1.5 py-0.5 text-[11px] text-ink-muted hover:border-accent disabled:opacity-40"
                    >
                      ＋
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

type TopPicksStrategy = "short_aggressive" | "long_conservative";
