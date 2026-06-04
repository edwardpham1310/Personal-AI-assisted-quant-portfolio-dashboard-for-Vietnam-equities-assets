"use client";

import { useMemo, useState } from "react";
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
import { RangeSelect } from "@/components/ui/RangeSelect";
import { Skeleton } from "@/components/ui/Skeleton";
import { useIndexComparison } from "@/hooks/useIndexComparison";
import { OHLCV_RANGE_OPTIONS, rangeToDays, type RangeKey } from "@/lib/dateRange";

export function IndexComparisonChart() {
  const [range, setRange] = useState<RangeKey>("3M");
  const days = useMemo(() => rangeToDays(range), [range]);
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
      action={
        <RangeSelect value={range} options={OHLCV_RANGE_OPTIONS} onChange={setRange} />
      }
    >
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
