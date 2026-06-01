"use client";

import { useMemo, useState } from "react";
import {
  STATUS_ORDER,
  isScannerRowStale,
  type ScannerResult,
  type SignalCode,
} from "@/hooks/useScanner";
import { EmptyState } from "@/components/ui/AsyncStates";
import { SignalBadgeList } from "./SignalBadge";
import { SignalFilterBar } from "./SignalFilterBar";
import { StatusBadge } from "./StatusBadge";
import { ScoreCell } from "./ScoreCell";
import { formatNumber } from "@/lib/format";

/**
 * A scanner row enriched with live-quote overlay. ``live_price`` overrides
 * the snapshot ``last_price`` and ``live_stale`` cooperates with the row's
 * own ``as_of`` to drive the "Stale" badge.
 */
export type ScannerRow = ScannerResult & {
  live_price?: number | null;
  live_stale?: boolean;
};

type ScoreKey = "trend" | "momentum" | "volume" | "liquidity" | "risk";

type SortKey = "symbol" | "status" | ScoreKey;
type SortDir = "asc" | "desc";

const TREND_TONE: Record<ScannerResult["trend"], string> = {
  UPTREND: "text-accent-up",
  DOWNTREND: "text-accent-down",
  SIDEWAYS: "text-ink-muted",
  UNKNOWN: "text-ink-dim",
};

function sortRows(rows: ScannerRow[], key: SortKey, dir: SortDir): ScannerRow[] {
  const mul = dir === "asc" ? 1 : -1;
  const copy = [...rows];
  copy.sort((a, b) => {
    let av: number | string;
    let bv: number | string;
    if (key === "symbol") {
      av = a.symbol;
      bv = b.symbol;
    } else if (key === "status") {
      av = STATUS_ORDER[a.status];
      bv = STATUS_ORDER[b.status];
    } else {
      av = a.scores[key];
      bv = b.scores[key];
    }
    if (av < bv) return -1 * mul;
    if (av > bv) return 1 * mul;
    return 0;
  });
  return copy;
}

function SortableTh({
  label,
  sortKey,
  current,
  dir,
  onSort,
  align = "left",
}: {
  label: string;
  sortKey: SortKey;
  current: SortKey;
  dir: SortDir;
  onSort: (key: SortKey) => void;
  align?: "left" | "right" | "center";
}) {
  const active = current === sortKey;
  const arrow = active ? (dir === "asc" ? "▲" : "▼") : "";
  const alignClass =
    align === "right" ? "text-right" : align === "center" ? "text-center" : "text-left";
  return (
    <th
      className={`py-1 ${alignClass}`}
      aria-sort={active ? (dir === "asc" ? "ascending" : "descending") : "none"}
    >
      <button
        type="button"
        onClick={() => onSort(sortKey)}
        className={`inline-flex items-center gap-1 text-xs ${
          active ? "text-ink" : "text-ink-dim"
        } hover:text-ink`}
      >
        {label}
        {arrow ? <span aria-hidden>{arrow}</span> : null}
      </button>
    </th>
  );
}

export function ScannerTable({
  rows,
  onRemove,
}: {
  rows: ScannerRow[];
  /** Optional remove callback. When absent, the Actions column is hidden. */
  onRemove?: (symbol: string) => void;
}) {
  const [sortKey, setSortKey] = useState<SortKey>("status");
  const [sortDir, setSortDir] = useState<SortDir>("asc");
  const [filters, setFilters] = useState<SignalCode[]>([]);

  function handleSort(key: SortKey) {
    if (key === sortKey) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortKey(key);
      // Scores: bigger is better → default desc. Status: lower index is
      // better → default asc. Symbol: alphabetical asc.
      setSortDir(key === "status" || key === "symbol" ? "asc" : "desc");
    }
  }

  const visible = useMemo(() => {
    const filtered =
      filters.length === 0 ? rows : rows.filter((r) => filters.every((f) => r.signals.includes(f)));
    return sortRows(filtered, sortKey, sortDir);
  }, [rows, filters, sortKey, sortDir]);

  return (
    <div className="space-y-3">
      <SignalFilterBar selected={filters} onChange={setFilters} />

      {rows.length === 0 ? (
        <EmptyState>
          No scanner results yet. Add a symbol to your watchlist to see signals.
        </EmptyState>
      ) : visible.length === 0 ? (
        <EmptyState>No symbols match the current filters.</EmptyState>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[980px] text-sm" aria-label="Scanner results">
            <thead>
              <tr className="border-b border-border text-xs text-ink-dim">
                <SortableTh
                  label="Symbol"
                  sortKey="symbol"
                  current={sortKey}
                  dir={sortDir}
                  onSort={handleSort}
                />
                <th className="py-1 text-right">Last</th>
                <th className="py-1 text-left">Trend</th>
                <SortableTh
                  label="Status"
                  sortKey="status"
                  current={sortKey}
                  dir={sortDir}
                  onSort={handleSort}
                />
                <th className="py-1 text-left">Signals</th>
                <SortableTh
                  label="Trend"
                  sortKey="trend"
                  current={sortKey}
                  dir={sortDir}
                  onSort={handleSort}
                  align="right"
                />
                <SortableTh
                  label="Momentum"
                  sortKey="momentum"
                  current={sortKey}
                  dir={sortDir}
                  onSort={handleSort}
                  align="right"
                />
                <SortableTh
                  label="Volume"
                  sortKey="volume"
                  current={sortKey}
                  dir={sortDir}
                  onSort={handleSort}
                  align="right"
                />
                <SortableTh
                  label="Liquidity"
                  sortKey="liquidity"
                  current={sortKey}
                  dir={sortDir}
                  onSort={handleSort}
                  align="right"
                />
                <SortableTh
                  label="Risk"
                  sortKey="risk"
                  current={sortKey}
                  dir={sortDir}
                  onSort={handleSort}
                  align="right"
                />
                <th className="py-1 text-center">Stale</th>
                {onRemove ? <th className="py-1 text-right">Actions</th> : null}
              </tr>
            </thead>
            <tbody>
              {visible.map((row) => (
                <ScannerRowView key={row.symbol} row={row} onRemove={onRemove} />
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function ScannerRowView({
  row,
  onRemove,
}: {
  row: ScannerRow;
  onRemove?: (symbol: string) => void;
}) {
  const lastPrice = row.live_price ?? row.last_price;
  const stale = row.live_stale === true || isScannerRowStale(row.as_of);
  const trendClass = TREND_TONE[row.trend];

  return (
    <tr data-testid={`scanner-row-${row.symbol}`} className="border-b border-border align-top">
      <td className="py-2 font-mono text-ink">{row.symbol}</td>
      <td className="py-2 text-right font-mono text-ink">
        {lastPrice != null ? formatNumber(lastPrice) : "—"}
      </td>
      <td className={`py-2 text-xs font-medium ${trendClass}`}>{row.trend}</td>
      <td className="py-2">
        <StatusBadge status={row.status} />
      </td>
      <td className="py-2">
        <SignalBadgeList codes={row.signals} />
      </td>
      <td className="py-2 text-right">
        <ScoreCell value={row.scores.trend} label={`${row.symbol} trend score`} />
      </td>
      <td className="py-2 text-right">
        <ScoreCell value={row.scores.momentum} label={`${row.symbol} momentum score`} />
      </td>
      <td className="py-2 text-right">
        <ScoreCell value={row.scores.volume} label={`${row.symbol} volume score`} />
      </td>
      <td className="py-2 text-right">
        <ScoreCell value={row.scores.liquidity} label={`${row.symbol} liquidity score`} />
      </td>
      <td className="py-2 text-right">
        <ScoreCell value={row.scores.risk} label={`${row.symbol} risk score`} />
      </td>
      <td className="py-2 text-center">
        {stale ? (
          <span
            className="inline-flex items-center rounded bg-amber-500/15 px-1.5 py-0.5 text-[10px] font-medium text-amber-300"
            title={`Last update ${new Date(row.as_of).toLocaleString()}`}
          >
            Stale
          </span>
        ) : (
          <span className="text-[10px] text-ink-dim">—</span>
        )}
      </td>
      {onRemove ? (
        <td className="py-2 text-right">
          <button
            type="button"
            onClick={() => onRemove(row.symbol)}
            className="text-xs text-ink-muted hover:text-accent-down"
            aria-label={`Remove ${row.symbol} from watchlist`}
          >
            Remove
          </button>
        </td>
      ) : null}
    </tr>
  );
}
