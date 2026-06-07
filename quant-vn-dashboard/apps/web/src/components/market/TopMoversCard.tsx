"use client";

import { useState } from "react";
import { Card } from "@/components/ui/Card";
import { Badge } from "@/components/ui/Badge";
import { EmptyState } from "@/components/ui/AsyncStates";
import type { Mover, TopMovers } from "@/lib/mock/market";
import { formatNumber, formatPct, formatVnd } from "@/lib/format";

type Tab = "gainers" | "losers" | "by_value" | "by_volume";

const TABS: { id: Tab; label: string }[] = [
  { id: "gainers", label: "Gainers" },
  { id: "losers", label: "Losers" },
  { id: "by_value", label: "By value" },
  { id: "by_volume", label: "Most active" },
];

function MoverRow({ row, tab }: { row: Mover; tab: Tab }) {
  return (
    <tr className="border-t border-border">
      <td className="py-1 font-mono">{row.symbol}</td>
      <td className="py-1 text-right font-mono">{formatNumber(row.price)}</td>
      <td
        className={`py-1 text-right font-mono ${
          row.change_pct > 0
            ? "text-accent-up"
            : row.change_pct < 0
              ? "text-accent-down"
              : "text-ink-dim"
        }`}
      >
        {formatPct(row.change_pct)}
      </td>
      <td className="py-1 text-right font-mono text-ink-dim">
        {tab === "by_value" && row.value != null
          ? formatVnd(row.value, { compact: true })
          : formatNumber(row.volume)}
      </td>
    </tr>
  );
}

export function TopMoversCard({ movers, isMock }: { movers: TopMovers; isMock: boolean }) {
  const [tab, setTab] = useState<Tab>("gainers");
  const rows = movers[tab];
  // Honest coverage label — these rankings are over the polled "tracked
  // universe" unless the backend confirms a full-market scan.
  const isFull = movers?.coverage === "full_market";
  const size = movers?.universe_size;
  const hint = isFull
    ? `Full market${size ? ` · ${size} symbols` : ""}`
    : `Tracked universe${size ? ` · ${size} symbols` : ""} — polled large caps, not the whole market`;
  return (
    <Card
      hint={hint}
      title={
        <>
          Top movers
          {isMock ? (
            <span className="ml-2">
              <Badge tone="mock">Mock</Badge>
            </span>
          ) : null}
        </>
      }
    >
      <div className="mb-2 flex flex-wrap gap-2">
        {TABS.map((t) => (
          <button
            key={t.id}
            onClick={() => setTab(t.id)}
            className={`rounded border px-2 py-0.5 text-xs transition-colors ${
              tab === t.id
                ? "border-accent text-accent"
                : "border-border text-ink-muted hover:border-ink-dim"
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>
      {rows.length === 0 ? (
        <EmptyState>No data.</EmptyState>
      ) : (
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-xs text-ink-dim">
              <th className="py-1">Symbol</th>
              <th className="py-1 text-right">Price</th>
              <th className="py-1 text-right">%</th>
              <th className="py-1 text-right">{tab === "by_value" ? "Value" : "Volume"}</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row, i) => (
              <MoverRow key={`${row.symbol}-${i}`} row={row} tab={tab} />
            ))}
          </tbody>
        </table>
      )}
      {tab === "by_volume" && rows.length > 0 ? (
        <p className="mt-2 text-[11px] text-ink-dim">
          Ranked by raw session volume (ordinal only — use “By value” for true
          liquidity).
        </p>
      ) : null}
    </Card>
  );
}
