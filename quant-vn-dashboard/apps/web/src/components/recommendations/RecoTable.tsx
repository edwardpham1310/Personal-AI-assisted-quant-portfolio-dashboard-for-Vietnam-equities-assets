"use client";

import { useMemo, useState } from "react";
import {
  ACTION_ORDER,
  type RecommendationAction,
  type RecommendationResult,
} from "@/hooks/useRecommendations";
import { formatNumber } from "@/lib/format";
import { ActionBadge, RecoStatusBadge } from "./ActionBadge";

type SortKey =
  | "symbol"
  | "action"
  | "confidence"
  | "final_score"
  | "last_price";

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
  filterActions: filterActionsProp,
  setFilterActions: setFilterActionsProp,
}: {
  results: RecommendationResult[];
  onSelect?: (rec: RecommendationResult) => void;
  filterActions?: Set<RecommendationAction>;
  setFilterActions?: (next: Set<RecommendationAction>) => void;
}) {
  const [sortKey, setSortKey] = useState<SortKey>("confidence");
  const [sortDir, setSortDir] = useState<SortDir>("desc");
  const [internalFilter, setInternalFilter] = useState<
    Set<RecommendationAction>
  >(new Set());
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
      <div
        className="flex flex-wrap gap-2"
        role="group"
        aria-label="Filter by action"
      >
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
              <Th onClick={() => toggleSort("confidence")} active={sortKey === "confidence"} dir={sortDir}>
                Confidence
              </Th>
              <Th onClick={() => toggleSort("final_score")} active={sortKey === "final_score"} dir={sortDir}>
                Score
              </Th>
              <Th onClick={() => toggleSort("last_price")} active={sortKey === "last_price"} dir={sortDir}>
                Last
              </Th>
              <th className="px-2 py-2">Entry</th>
              <th className="px-2 py-2">Stop</th>
              <th className="px-2 py-2">TP</th>
              <th className="px-2 py-2 text-right">Size (VND)</th>
              <th className="px-2 py-2 text-right">Qty</th>
              <th className="px-2 py-2">Status</th>
              <th className="px-2 py-2">Warnings</th>
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
                <td className="px-2 py-2 font-mono text-ink">{r.symbol}</td>
                <td className="px-2 py-2">
                  <ActionBadge action={r.action} />
                </td>
                <td className="px-2 py-2 font-mono">
                  {(r.confidence * 100).toFixed(0)}%
                </td>
                <td className="px-2 py-2 font-mono">{r.final_score}</td>
                <td className="px-2 py-2 font-mono">
                  {r.last_price != null ? formatNumber(r.last_price) : "—"}
                </td>
                <td className="px-2 py-2 font-mono text-xs">
                  {r.entry_zone_low != null && r.entry_zone_high != null
                    ? `${formatNumber(r.entry_zone_low)}–${formatNumber(
                        r.entry_zone_high,
                      )}`
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
                  {r.position_size_vnd != null
                    ? formatNumber(r.position_size_vnd)
                    : "—"}
                </td>
                <td className="px-2 py-2 text-right font-mono">
                  {r.estimated_quantity != null
                    ? formatNumber(r.estimated_quantity)
                    : "—"}
                </td>
                <td className="px-2 py-2">
                  <RecoStatusBadge status={r.status} />
                </td>
                <td className="px-2 py-2 text-xs text-amber-400">
                  {r.warnings.length > 0 ? `${r.warnings.length}` : "—"}
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
        className={`flex items-center gap-1 hover:text-ink ${
          active ? "text-ink" : ""
        }`}
        aria-sort={active ? (dir === "asc" ? "ascending" : "descending") : "none"}
      >
        {children}
        {active ? (
          <span className="text-[10px]">{dir === "asc" ? "▲" : "▼"}</span>
        ) : null}
      </button>
    </th>
  );
}
