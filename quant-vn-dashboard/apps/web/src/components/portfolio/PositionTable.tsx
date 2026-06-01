"use client";

import { useMemo, useState } from "react";
import { EmptyState } from "@/components/ui/AsyncStates";
import { formatNumber } from "@/lib/format";
import type { EnrichedPosition } from "@/hooks/portfolio-types";

type SortKey =
  | "symbol"
  | "quantity"
  | "sellable_quantity"
  | "pending_quantity"
  | "avg_cost"
  | "market_price"
  | "market_value"
  | "unrealized_pnl"
  | "unrealized_pnl_pct"
  | "weight";

type SortDir = "asc" | "desc";

function compareNullable(a: number | null, b: number | null): number {
  // Treat null as smaller than any number so DESC puts real values first.
  if (a == null && b == null) return 0;
  if (a == null) return -1;
  if (b == null) return 1;
  return a - b;
}

function sortRows(rows: EnrichedPosition[], key: SortKey, dir: SortDir): EnrichedPosition[] {
  const mul = dir === "asc" ? 1 : -1;
  const copy = [...rows];
  copy.sort((a, b) => {
    if (key === "symbol") return a.symbol.localeCompare(b.symbol) * mul;
    return compareNullable(a[key] as number | null, b[key] as number | null) * mul;
  });
  return copy;
}

function pnlClass(value: number | null): string {
  if (value == null) return "text-ink-dim";
  if (value > 0) return "text-accent-up";
  if (value < 0) return "text-accent-down";
  return "text-ink-muted";
}

function NullableNumberCell({ value, warning }: { value: number | null; warning?: string }) {
  if (value == null) {
    return (
      <span
        className="text-ink-dim"
        title={warning ?? "No mark-to-market price available."}
        aria-label={warning ?? "No mark-to-market price available."}
      >
        —
      </span>
    );
  }
  return <span className="font-mono">{formatNumber(value)}</span>;
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

export type PositionTableProps = {
  rows: EnrichedPosition[];
  onEdit?: (position: EnrichedPosition) => void;
  onDelete?: (position: EnrichedPosition) => void;
};

export function PositionTable({ rows, onEdit, onDelete }: PositionTableProps) {
  const [sortKey, setSortKey] = useState<SortKey>("weight");
  const [sortDir, setSortDir] = useState<SortDir>("desc");

  function handleSort(key: SortKey) {
    if (key === sortKey) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortKey(key);
      setSortDir(key === "symbol" ? "asc" : "desc");
    }
  }

  const visible = useMemo(() => sortRows(rows, sortKey, sortDir), [rows, sortKey, sortDir]);

  if (rows.length === 0) {
    return <EmptyState>No positions yet. Add one to start tracking your portfolio.</EmptyState>;
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[1100px] text-sm" aria-label="Portfolio positions">
        <thead>
          <tr className="border-b border-border text-xs text-ink-dim">
            <SortableTh
              label="Symbol"
              sortKey="symbol"
              current={sortKey}
              dir={sortDir}
              onSort={handleSort}
            />
            <th className="py-1 text-left">Exch</th>
            <SortableTh
              label="Qty"
              sortKey="quantity"
              current={sortKey}
              dir={sortDir}
              onSort={handleSort}
              align="right"
            />
            <SortableTh
              label="Sellable"
              sortKey="sellable_quantity"
              current={sortKey}
              dir={sortDir}
              onSort={handleSort}
              align="right"
            />
            <SortableTh
              label="Pending"
              sortKey="pending_quantity"
              current={sortKey}
              dir={sortDir}
              onSort={handleSort}
              align="right"
            />
            <SortableTh
              label="Avg cost"
              sortKey="avg_cost"
              current={sortKey}
              dir={sortDir}
              onSort={handleSort}
              align="right"
            />
            <SortableTh
              label="Last px"
              sortKey="market_price"
              current={sortKey}
              dir={sortDir}
              onSort={handleSort}
              align="right"
            />
            <SortableTh
              label="Mkt value"
              sortKey="market_value"
              current={sortKey}
              dir={sortDir}
              onSort={handleSort}
              align="right"
            />
            <SortableTh
              label="Unrealized"
              sortKey="unrealized_pnl"
              current={sortKey}
              dir={sortDir}
              onSort={handleSort}
              align="right"
            />
            <SortableTh
              label="Unrealized %"
              sortKey="unrealized_pnl_pct"
              current={sortKey}
              dir={sortDir}
              onSort={handleSort}
              align="right"
            />
            <SortableTh
              label="Weight"
              sortKey="weight"
              current={sortKey}
              dir={sortDir}
              onSort={handleSort}
              align="right"
            />
            <th className="py-1 text-left">Strategy</th>
            <th className="py-1 text-left">Note</th>
            {onEdit || onDelete ? <th className="py-1 text-right">Actions</th> : null}
          </tr>
        </thead>
        <tbody>
          {visible.map((row) => {
            const warning = row.warnings[0];
            return (
              <tr
                key={row.id}
                data-testid={`position-row-${row.symbol}`}
                className="border-b border-border align-top"
              >
                <td className="py-2 font-mono text-ink">
                  {row.symbol}
                  {warning ? (
                    <span
                      className="ml-1 inline-flex items-center rounded bg-amber-500/15 px-1 py-0.5 text-[9px] font-medium text-amber-300"
                      title={warning}
                      aria-label={`Warning: ${warning}`}
                    >
                      !
                    </span>
                  ) : null}
                </td>
                <td className="py-2 text-xs text-ink-muted">{row.exchange}</td>
                <td className="py-2 text-right font-mono">{formatNumber(row.quantity)}</td>
                <td className="py-2 text-right font-mono">{formatNumber(row.sellable_quantity)}</td>
                <td className="py-2 text-right font-mono text-ink-dim">
                  {row.pending_quantity > 0 ? formatNumber(row.pending_quantity) : "—"}
                </td>
                <td className="py-2 text-right font-mono">{formatNumber(row.avg_cost)}</td>
                <td className="py-2 text-right">
                  <NullableNumberCell value={row.market_price} warning={warning} />
                </td>
                <td className="py-2 text-right">
                  <NullableNumberCell value={row.market_value} warning={warning} />
                </td>
                <td className={`py-2 text-right font-mono ${pnlClass(row.unrealized_pnl)}`}>
                  {row.unrealized_pnl == null
                    ? "—"
                    : `${row.unrealized_pnl >= 0 ? "+" : ""}${formatNumber(row.unrealized_pnl)}`}
                </td>
                <td className={`py-2 text-right font-mono ${pnlClass(row.unrealized_pnl_pct)}`}>
                  {row.unrealized_pnl_pct == null
                    ? "—"
                    : `${row.unrealized_pnl_pct >= 0 ? "+" : ""}${row.unrealized_pnl_pct.toFixed(2)}%`}
                </td>
                <td className="py-2 text-right font-mono text-ink-dim">
                  {row.weight == null ? "—" : `${row.weight.toFixed(2)}%`}
                </td>
                <td className="py-2 text-xs text-ink-muted">{row.strategy_tag ?? "—"}</td>
                <td
                  className="py-2 text-xs text-ink-dim max-w-[160px] truncate"
                  title={row.note ?? undefined}
                >
                  {row.note ?? "—"}
                </td>
                {onEdit || onDelete ? (
                  <td className="py-2 text-right">
                    <div className="inline-flex gap-2">
                      {onEdit ? (
                        <button
                          type="button"
                          onClick={() => onEdit(row)}
                          className="text-xs text-ink-muted hover:text-accent"
                          aria-label={`Edit ${row.symbol}`}
                        >
                          Edit
                        </button>
                      ) : null}
                      {onDelete ? (
                        <button
                          type="button"
                          onClick={() => onDelete(row)}
                          className="text-xs text-ink-muted hover:text-accent-down"
                          aria-label={`Delete ${row.symbol}`}
                        >
                          Delete
                        </button>
                      ) : null}
                    </div>
                  </td>
                ) : null}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
