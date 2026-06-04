"use client";

import { Card } from "@/components/ui/Card";
import { Badge } from "@/components/ui/Badge";
import type { MarketBreadth } from "@/lib/mock/market";

function Cell({
  label,
  value,
  tone,
}: {
  label: string;
  value: number;
  tone: "up" | "down" | "neutral";
}) {
  return (
    <div className="flex flex-col items-start">
      <span className="text-xs text-ink-dim uppercase tracking-wider">{label}</span>
      <span
        className={`font-mono text-xl ${
          tone === "up" ? "text-accent-up" : tone === "down" ? "text-accent-down" : "text-ink"
        }`}
      >
        {value}
      </span>
    </div>
  );
}

export function MarketBreadthCard({
  breadth,
  isMock,
}: {
  breadth: MarketBreadth;
  isMock: boolean;
}) {
  // Defensive: coerce each field so a partial/missing payload renders 0,
  // never NaN% (the poller can return a sparse object on a cold cache).
  const advancers = Number(breadth?.advancers) || 0;
  const decliners = Number(breadth?.decliners) || 0;
  const unchanged = Number(breadth?.unchanged) || 0;
  const ceiling = Number(breadth?.ceiling) || 0;
  const floor = Number(breadth?.floor) || 0;
  const total = advancers + decliners + unchanged || 1;
  const advRatio = advancers / total;

  return (
    <Card
      title={
        <>
          Market breadth
          {isMock ? (
            <span className="ml-2">
              <Badge tone="mock">Mock</Badge>
            </span>
          ) : null}
        </>
      }
      hint="Counts across HOSE / HNX / UPCoM"
    >
      <div className="grid grid-cols-3 gap-3 sm:grid-cols-5">
        <Cell label="Advancers" value={advancers} tone="up" />
        <Cell label="Decliners" value={decliners} tone="down" />
        <Cell label="Unchanged" value={unchanged} tone="neutral" />
        <Cell label="Ceiling" value={ceiling} tone="up" />
        <Cell label="Floor" value={floor} tone="down" />
      </div>
      <div className="mt-3 h-2 w-full overflow-hidden rounded bg-bg-subtle">
        <div
          className="h-full bg-accent-up"
          style={{ width: `${Math.round(advRatio * 100)}%` }}
          aria-label={`Advancers ${Math.round(advRatio * 100)}%`}
        />
      </div>
      <p className="mt-1 text-[10px] text-ink-dim">
        {Math.round(advRatio * 100)}% advancing of {total} symbols
      </p>
    </Card>
  );
}
