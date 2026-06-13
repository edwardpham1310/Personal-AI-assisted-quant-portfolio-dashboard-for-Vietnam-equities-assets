"use client";

import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from "recharts";
import { Card } from "@/components/ui/Card";
import { EmptyState } from "@/components/ui/AsyncStates";
import { StaleNote } from "@/components/ui/StaleNote";
import type { EquityPoint } from "@/lib/mock/portfolio";
import { formatVnd } from "@/lib/format";
import { AXIS_TICK, CHART_COLORS, GRID_STROKE, TOOLTIP_LABEL_STYLE, TOOLTIP_STYLE } from "@/lib/chart";
import type { ReactNode } from "react";

export function EquityCurveChart({
  data = [],
  action,
  title = "Portfolio equity curve",
  asOf,
  stale = false,
}: {
  data?: EquityPoint[];
  action?: ReactNode;
  title?: string;
  asOf?: string | null;
  stale?: boolean;
}) {
  return (
    <Card title={title} hint="Daily NAV — forward-only history" action={action}>
      {data.length === 0 ? (
        <EmptyState>No portfolio history yet.</EmptyState>
      ) : (
        <>
          <div className="h-56">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
                <CartesianGrid stroke={GRID_STROKE} vertical={false} />
                <XAxis dataKey="ts" tick={AXIS_TICK} minTickGap={32} />
                <YAxis
                  tick={AXIS_TICK}
                  width={70}
                  tickFormatter={(v: number) => formatVnd(v, { compact: true })}
                />
                <Tooltip
                  contentStyle={TOOLTIP_STYLE}
                  labelStyle={TOOLTIP_LABEL_STYLE}
                  formatter={(v: number) => formatVnd(v)}
                />
                <Line
                  type="monotone"
                  dataKey="equity"
                  stroke={CHART_COLORS.primary}
                  strokeWidth={2}
                  dot={false}
                  connectNulls
                />
              </LineChart>
            </ResponsiveContainer>
          </div>
          <StaleNote asOf={asOf} stale={stale} />
        </>
      )}
    </Card>
  );
}
