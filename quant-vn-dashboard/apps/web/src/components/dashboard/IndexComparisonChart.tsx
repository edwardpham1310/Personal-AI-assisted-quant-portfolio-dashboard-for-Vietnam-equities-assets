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
import { StaleNote } from "@/components/ui/StaleNote";
import { useIndexComparison } from "@/hooks/useIndexComparison";
import { OHLCV_RANGE_OPTIONS, rangeToDays, type RangeKey } from "@/lib/dateRange";
import { AXIS_TICK, CHART_COLORS, GRID_STROKE, TOOLTIP_LABEL_STYLE, TOOLTIP_STYLE } from "@/lib/chart";

export function IndexComparisonChart() {
  const [range, setRange] = useState<RangeKey>("3M");
  const days = useMemo(() => rangeToDays(range), [range]);
  const { data, isLoading, error, isMock, stale, lastUpdatedAt, hasLoadedReal } =
    useIndexComparison(days);
  // Keep the last good chart visible on a refetch error; only show error/empty
  // when we have never loaded real data.
  const showChart = data.length > 0 && hasLoadedReal;

  return (
    <Card
      title={
        <span className="inline-flex items-center gap-2">
          VNINDEX vs VN30
          {isMock ? <Badge tone="mock">Mock</Badge> : null}
        </span>
      }
      hint="Rebased to 100"
      action={<RangeSelect value={range} options={OHLCV_RANGE_OPTIONS} onChange={setRange} />}
    >
      {isLoading && !hasLoadedReal ? (
        <Skeleton height={224} />
      ) : !showChart && error ? (
        <p className="text-xs text-accent-down">{error}</p>
      ) : !showChart ? (
        <EmptyState>No index comparison data yet.</EmptyState>
      ) : (
        <>
          <div className="h-56">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
                <CartesianGrid stroke={GRID_STROKE} vertical={false} />
                <XAxis dataKey="ts" tick={AXIS_TICK} minTickGap={32} />
                <YAxis tick={AXIS_TICK} width={48} domain={["auto", "auto"]} />
                <Tooltip
                  contentStyle={TOOLTIP_STYLE}
                  labelStyle={TOOLTIP_LABEL_STYLE}
                  formatter={(v: number) => (typeof v === "number" ? v.toFixed(2) : "—")}
                />
                <Legend wrapperStyle={{ fontSize: 11 }} />
                <Line
                  type="monotone"
                  dataKey="vnindex"
                  name="VNINDEX"
                  stroke={CHART_COLORS.primary}
                  strokeWidth={2}
                  dot={false}
                  connectNulls
                />
                <Line
                  type="monotone"
                  dataKey="vn30"
                  name="VN30"
                  stroke={CHART_COLORS.up}
                  strokeWidth={2}
                  dot={false}
                  connectNulls
                />
              </LineChart>
            </ResponsiveContainer>
          </div>
          <StaleNote asOf={lastUpdatedAt} stale={stale} />
        </>
      )}
    </Card>
  );
}
