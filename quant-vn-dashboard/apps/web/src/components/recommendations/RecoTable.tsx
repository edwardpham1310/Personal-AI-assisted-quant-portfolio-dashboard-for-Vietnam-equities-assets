"use client";

import { useMemo, useState } from "react";
import {
  ACTION_ORDER,
  type DataStatus,
  type RecommendationAction,
  type RecommendationResult,
} from "@/hooks/useRecommendations";
import { formatNumber } from "@/lib/format";
import { ActionBadge, RecoStatusBadge } from "./ActionBadge";

// Phase 2 data-status badge. Surfaces FRESH / STALE / DATA_UNAVAILABLE /
// PROVIDER_ERROR right next to the symbol so the operator can tell at a
// glance whether the recommendation is backed by real data.
const DATA_STATUS_META: Record<DataStatus, { label: string; cls: string; title: string }> = {
  FRESH: {
    label: "FRESH",
    cls: "bg-accent-up/15 text-accent-up border-accent-up/40",
    title: "Live data from SSI; quote within freshness window.",
  },
  STALE: {
    label: "STALE",
    cls: "bg-amber-500/15 text-amber-400 border-amber-500/40",
    title: "Data older than the freshness window. Reload to refresh.",
  },
  DATA_UNAVAILABLE: {
    label: "NO DATA",
    cls: "bg-accent-down/15 text-accent-down border-accent-down/40",
    title: "Market data unavailable for this symbol — recommendation neutered.",
  },
  PROVIDER_ERROR: {
    label: "PROVIDER ERR",
    cls: "bg-accent-down/25 text-accent-down border-accent-down/60",
    title: "Upstream SSI provider error. See /data-quality for detail.",
  },
};

// Feature 7: flags a symbol you already hold, with its weight within holdings.
// A high weight (engine flags it via the portfolio_concentration warning) turns
// the badge amber to surface concentration risk inline.
function HeldBadge({ rec }: { rec: RecommendationResult }) {
  const concentrated = rec.warnings.includes("portfolio_concentration");
  const pct = rec.held_weight_pct;
  const cls = concentrated
    ? "bg-amber-500/15 text-amber-400 border-amber-500/40"
    : "bg-accent/15 text-accent border-accent/40";
  return (
    <span
      title={rec.portfolio_note ?? "Currently held"}
      className={`inline-flex items-center rounded border px-1.5 py-0.5 text-[9px] font-medium uppercase tracking-tight ${cls}`}
    >
      Held{pct != null ? ` ${pct.toFixed(0)}%` : ""}
    </span>
  );
}

function DataStatusBadge({ status }: { status: DataStatus }) {
  const meta = DATA_STATUS_META[status];
  return (
    <span
      data-data-status={status}
      title={meta.title}
      className={`inline-flex items-center rounded border px-1.5 py-0.5 text-[9px] font-medium uppercase tracking-tight ${meta.cls}`}
    >
      {meta.label}
    </span>
  );
}

type SortKey = "symbol" | "action" | "confidence" | "final_score" | "last_price";

type SortDir = "asc" | "desc";

const ALL_ACTIONS: RecommendationAction[] = [
  "BUY_CANDIDATE",
  "WATCH",
  "HOLD",
  "REDUCE",
  "SELL_CANDIDATE",
  "AVOID",
  "REJECTED",
];

function compareValues(a: number | string | null, b: number | string | null): number {
  if (a == null && b == null) return 0;
  if (a == null) return 1;
  if (b == null) return -1;
  if (typeof a === "string" && typeof b === "string") return a.localeCompare(b);
  return Number(a) - Number(b);
}

export function RecoTable({
  results,
  onSelect,
  onSendToPaper,
  filterActions: filterActionsProp,
  setFilterActions: setFilterActionsProp,
}: {
  results: RecommendationResult[];
  onSelect?: (rec: RecommendationResult) => void;
  /** Phase 2.7 hook: opens a paper-trade confirmation flow for this rec.
   *  Optional so existing call sites + tests keep working unchanged. */
  onSendToPaper?: (rec: RecommendationResult) => void;
  filterActions?: Set<RecommendationAction>;
  setFilterActions?: (next: Set<RecommendationAction>) => void;
}) {
  const [sortKey, setSortKey] = useState<SortKey>("confidence");
  const [sortDir, setSortDir] = useState<SortDir>("desc");
  const [internalFilter, setInternalFilter] = useState<Set<RecommendationAction>>(new Set());
  const filterActions = filterActionsProp ?? internalFilter;
  const setFilterActions = setFilterActionsProp ?? setInternalFilter;

  const filtered = useMemo(() => {
    if (filterActions.size === 0) return results;
    return results.filter((r) => filterActions.has(r.action));
  }, [results, filterActions]);

  const sorted = useMemo(() => {
    const dir = sortDir === "asc" ? 1 : -1;
    const arr = [...filtered];
    arr.sort((a, b) => {
      if (sortKey === "action") {
        return (ACTION_ORDER[a.action] - ACTION_ORDER[b.action]) * dir;
      }
      const av = a[sortKey] as number | string | null;
      const bv = b[sortKey] as number | string | null;
      return compareValues(av, bv) * dir;
    });
    return arr;
  }, [filtered, sortKey, sortDir]);

  const toggleSort = (key: SortKey) => {
    if (key === sortKey) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortKey(key);
      setSortDir(key === "symbol" ? "asc" : "desc");
    }
  };

  const toggleFilter = (action: RecommendationAction) => {
    const next = new Set(filterActions);
    if (next.has(action)) next.delete(action);
    else next.add(action);
    setFilterActions(next);
  };

  if (results.length === 0) {
    return (
      <div className="rounded border border-border bg-bg-panel p-6 text-center">
        <p className="text-sm text-ink-dim">
          No recommendations yet. Pick a watchlist or symbol above.
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap gap-2" role="group" aria-label="Filter by action">
        {ALL_ACTIONS.map((action) => {
          const active = filterActions.has(action);
          return (
            <button
              key={action}
              type="button"
              onClick={() => toggleFilter(action)}
              aria-pressed={active}
              className={`rounded-full border px-2 py-0.5 text-[10px] ${
                active
                  ? "border-accent bg-accent/15 text-accent"
                  : "border-border text-ink-dim hover:border-accent"
              }`}
            >
              {action}
            </button>
          );
        })}
      </div>

      <div className="overflow-x-auto rounded border border-border bg-bg-panel">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-xs text-ink-dim">
              <Th onClick={() => toggleSort("symbol")} active={sortKey === "symbol"} dir={sortDir}>
                Symbol
              </Th>
              <Th onClick={() => toggleSort("action")} active={sortKey === "action"} dir={sortDir}>
                Action
              </Th>
              <Th
                onClick={() => toggleSort("confidence")}
                active={sortKey === "confidence"}
                dir={sortDir}
              >
                Confidence
              </Th>
              <Th
                onClick={() => toggleSort("final_score")}
                active={sortKey === "final_score"}
                dir={sortDir}
              >
                Score
              </Th>
              <Th
                onClick={() => toggleSort("last_price")}
                active={sortKey === "last_price"}
                dir={sortDir}
              >
                Last
              </Th>
              <th className="px-2 py-2">Entry</th>
              <th className="px-2 py-2">Stop</th>
              <th className="px-2 py-2">TP</th>
              <th className="px-2 py-2 text-right">Size (VND)</th>
              <th className="px-2 py-2 text-right">Qty</th>
              <th className="px-2 py-2">Status</th>
              <th className="px-2 py-2">Warnings</th>
              <th className="px-2 py-2">Chart</th>
            </tr>
          </thead>
          <tbody>
            {sorted.map((r) => (
              <tr
                key={`${r.symbol}-${r.profile}-${r.horizon}`}
                onClick={() => onSelect?.(r)}
                role={onSelect ? "button" : undefined}
                tabIndex={onSelect ? 0 : undefined}
                className="cursor-pointer border-t border-border hover:bg-bg-subtle/40"
                data-testid={`reco-row-${r.symbol}`}
              >
                <td className="px-2 py-2 font-mono text-ink">
                  <div className="flex items-center gap-1">
                    <span>{r.symbol}</span>
                    <DataStatusBadge status={r.data_status} />
                    {r.is_held ? <HeldBadge rec={r} /> : null}
                  </div>
                </td>
                <td className="px-2 py-2">
                  <ActionBadge action={r.action} />
                </td>
                <td className="px-2 py-2 font-mono">{(r.confidence * 100).toFixed(0)}%</td>
                <td className="px-2 py-2 font-mono">{r.final_score}</td>
                <td className="px-2 py-2 font-mono">
                  {r.last_price != null ? formatNumber(r.last_price) : "—"}
                  {r.latest_quote?.change_pct != null ? (
                    <span
                      className={`ml-1 text-[10px] ${
                        r.latest_quote.change_pct >= 0 ? "text-accent-up" : "text-accent-down"
                      }`}
                    >
                      {r.latest_quote.change_pct >= 0 ? "+" : ""}
                      {r.latest_quote.change_pct.toFixed(2)}%
                    </span>
                  ) : null}
                </td>
                <td className="px-2 py-2 font-mono text-xs">
                  {r.entry_zone_low != null && r.entry_zone_high != null
                    ? `${formatNumber(r.entry_zone_low)}–${formatNumber(r.entry_zone_high)}`
                    : "—"}
                </td>
                <td className="px-2 py-2 font-mono text-xs">
                  {r.stop_loss != null ? formatNumber(r.stop_loss) : "—"}
                </td>
                <td className="px-2 py-2 font-mono text-xs">
                  {r.take_profit_1 != null && r.take_profit_2 != null
                    ? `${formatNumber(r.take_profit_1)} / ${formatNumber(r.take_profit_2)}`
                    : "—"}
                </td>
                <td className="px-2 py-2 text-right font-mono">
                  {r.position_size_vnd != null ? formatNumber(r.position_size_vnd) : "—"}
                </td>
                <td className="px-2 py-2 text-right font-mono">
                  {r.estimated_quantity != null ? formatNumber(r.estimated_quantity) : "—"}
                </td>
                <td className="px-2 py-2">
                  <RecoStatusBadge status={r.status} />
                </td>
                <td className="px-2 py-2 text-xs text-amber-400">
                  {r.warnings.length > 0 ? `${r.warnings.length}` : "—"}
                </td>
                <td className="px-2 py-2 text-xs">
                  <div className="flex gap-2 items-center">
                    <a
                      href={r.chart_url || `/market/${r.symbol}`}
                      onClick={(e) => e.stopPropagation()}
                      className="text-accent hover:underline"
                      aria-label={`View chart for ${r.symbol}`}
                    >
                      View chart
                    </a>
                    {onSendToPaper ? (
                      <button
                        type="button"
                        data-testid={`send-to-paper-${r.symbol}`}
                        onClick={(e) => {
                          e.stopPropagation();
                          onSendToPaper(r);
                        }}
                        className="rounded border border-accent/40 bg-accent/10 px-2 py-0.5 text-[10px] text-accent hover:bg-accent/20"
                        aria-label={`Send ${r.symbol} to paper trading`}
                      >
                        Send to Paper Trade
                      </button>
                    ) : null}
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="text-[10px] text-ink-dim">
        Research signals · Rule-based · Not financial advice · No orders placed.
      </p>
    </div>
  );
}

function Th({
  children,
  onClick,
  active,
  dir,
}: {
  children: React.ReactNode;
  onClick: () => void;
  active: boolean;
  dir: SortDir;
}) {
  return (
    <th className="px-2 py-2">
      <button
        type="button"
        onClick={onClick}
        className={`flex items-center gap-1 hover:text-ink ${active ? "text-ink" : ""}`}
        aria-sort={active ? (dir === "asc" ? "ascending" : "descending") : "none"}
      >
        {children}
        {active ? <span className="text-[10px]">{dir === "asc" ? "▲" : "▼"}</span> : null}
      </button>
    </th>
  );
}
