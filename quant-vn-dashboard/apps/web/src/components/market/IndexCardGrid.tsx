"use client";

import { Badge } from "@/components/ui/Badge";
import { Skeleton } from "@/components/ui/Skeleton";
import type { IndexSnapshot } from "@/lib/mock/market";
import { formatNumber, formatPct, signedColor } from "@/lib/format";

export function IndexCardGrid({
  indices,
  loading,
}: {
  indices: IndexSnapshot[];
  loading: boolean;
}) {
  return (
    <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
      {indices.map((idx) => {
        const tone = signedColor(idx.change);
        return (
          <div key={idx.code} className="rounded-lg border border-border bg-bg-panel px-4 py-3">
            <div className="flex items-baseline justify-between">
              <p className="text-sm font-medium text-ink">{idx.code}</p>
              <Badge tone={tone}>{formatPct(idx.change_pct)}</Badge>
            </div>
            <p className="mt-1 font-mono text-2xl text-ink">
              {loading ? <Skeleton height={24} width={96} /> : idx.close.toFixed(2)}
            </p>
            <p
              className={`text-xs font-mono ${tone === "up" ? "text-accent-up" : tone === "down" ? "text-accent-down" : "text-ink-dim"}`}
            >
              {idx.change >= 0 ? "+" : ""}
              {idx.change.toFixed(2)}
            </p>
            <p className="mt-1 text-[10px] text-ink-dim">vol {formatNumber(idx.volume)}</p>
          </div>
        );
      })}
    </div>
  );
}
