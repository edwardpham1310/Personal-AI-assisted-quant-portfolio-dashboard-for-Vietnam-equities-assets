"use client";

import { useState } from "react";
import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { Card } from "@/components/ui/Card";
import { EmptyState } from "@/components/ui/AsyncStates";
import { Skeleton } from "@/components/ui/Skeleton";
import { RangeSelect } from "@/components/ui/RangeSelect";
import { usePortfolioVsIndex } from "@/hooks/usePortfolioVsIndex";
import { OHLCV_RANGE_OPTIONS, type RangeKey } from "@/lib/dateRange";

/**
 * Real portfolio NAV vs VNINDEX, rebased to 100. Both series are real
 * (forward-only equity-curve snapshots + VNINDEX daily OHLCV); the panel shows
 * an honest empty state until the curve has at least one snapshot overlapping a
 * VNINDEX trading day. Capped at 1Y because VNINDEX daily history is.
 */
export function PortfolioVsVnindexChart() {
  const [range, setRange] = useState<RangeKey>("3M");
  const { data, loading, error } = usePortfolioVsIndex(range);

  return (
    <Card
      title="Portfolio vs VNINDEX"
      hint="Rebased to 100 — research only"
      action={
        <RangeSelect value={range} options={OHLCV_RANGE_OPTIONS} onChange={setRange} />
      }
    >
      {loading && data.length === 0 ? (
        <Skeleton height={224} />
      ) : error ? (
        <p className="text-xs text-accent-down">{error}</p>
      ) : data.length === 0 ? (
        <EmptyState>
          No portfolio history yet — the equity curve seeds as you use the dashboard.
        </EmptyState>
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
                dataKey="portfolio"
                name="Portfolio"
                stroke="#4f8bf0"
                strokeWidth={2}
                dot={false}
              />
              <Line
                type="monotone"
                dataKey="vnindex"
                name="VNINDEX"
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
