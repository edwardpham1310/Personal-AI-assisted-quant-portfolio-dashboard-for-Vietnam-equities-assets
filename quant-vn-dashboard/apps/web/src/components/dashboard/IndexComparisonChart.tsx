"use client";

import { useState } from "react";
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
} from "recharts";
import { Card } from "@/components/ui/Card";
import { EmptyState } from "@/components/ui/AsyncStates";
import { Badge } from "@/components/ui/Badge";
import { Skeleton } from "@/components/ui/Skeleton";
import { useIndexComparison } from "@/hooks/useIndexComparison";

// Days-since-Jan-1 for the YTD button, clamped to the backend's 365-day cap.
function ytdDays(): number {
  const now = new Date();
  const jan1 = new Date(now.getFullYear(), 0, 1);
  return Math.min(365, Math.max(1, Math.ceil((now.getTime() - jan1.getTime()) / 86_400_000) + 1));
}

const RANGES: { label: string; days: number }[] = [
  { label: "1M", days: 30 },
  { label: "3M", days: 90 },
  { label: "6M", days: 180 },
  { label: "1Y", days: 365 },
  { label: "YTD", days: ytdDays() },
];

export function IndexComparisonChart() {
  const [days, setDays] = useState(90);
  const { data, isLoading, error, isMock } = useIndexComparison(days);

  return (
    <Card
      title={
        <span className="inline-flex items-center gap-2">
          VNINDEX vs VN30
          {isMock ? <Badge tone="mock">Mock</Badge> : null}
        </span>
      }
      hint="Rebased to 100"
    >
      <div className="mb-3 flex justify-end gap-1">
        {RANGES.map((r) => (
          <button
            key={r.label}
            onClick={() => setDays(r.days)}
            className={`rounded border px-2 py-0.5 text-xs ${
              days === r.days
                ? "border-accent text-accent"
                : "border-border text-ink-muted hover:border-ink-dim"
            }`}
          >
            {r.label}
          </button>
        ))}
      </div>

      {isLoading ? (
        <Skeleton height={224} />
      ) : error ? (
        <p className="text-xs text-accent-down">{error}</p>
      ) : data.length === 0 ? (
        <EmptyState>No index comparison data yet.</EmptyState>
      ) : (
        <div className="h-56">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
              <CartesianGrid stroke="#21262d" vertical={false} />
              <XAxis dataKey="ts" tick={{ fill: "#8b949e", fontSize: 10 }} minTickGap={32} />
              <YAxis tick={{ fill: "#8b949e", fontSize: 10 }} width={48} domain={["auto", "auto"]} />
              <Tooltip
                contentStyle={{ background: "#0b0d10", border: "1px solid #21262d", fontSize: 12 }}
                labelStyle={{ color: "#e6edf3" }}
                formatter={(v: number) => v.toFixed(2)}
              />
              <Legend wrapperStyle={{ fontSize: 11 }} />
              <Line
                type="monotone"
                dataKey="vnindex"
                name="VNINDEX"
                stroke="#4f8bf0"
                strokeWidth={2}
                dot={false}
              />
              <Line
                type="monotone"
                dataKey="vn30"
                name="VN30"
                stroke="#22c55e"
                strokeWidth={2}
                dot={false}
              />
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}
    </Card>
  );
}
