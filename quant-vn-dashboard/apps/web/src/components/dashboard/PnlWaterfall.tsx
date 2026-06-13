"use client";

import {
  BarChart,
  Bar,
  Cell,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from "recharts";
import { Card } from "@/components/ui/Card";
import { EmptyState } from "@/components/ui/AsyncStates";
import { StaleNote } from "@/components/ui/StaleNote";
import type { PnlBucket } from "@/lib/mock/portfolio";
import { formatVnd } from "@/lib/format";
import { AXIS_TICK, CHART_COLORS, GRID_STROKE, TOOLTIP_STYLE } from "@/lib/chart";

export function PnlWaterfall({
  data = [],
  asOf,
  stale = false,
}: {
  data?: PnlBucket[];
  asOf?: string | null;
  stale?: boolean;
}) {
  return (
    <Card title="PnL by bucket" hint="Realized + unrealized − costs → net contribution">
      {data.length === 0 ? (
        <EmptyState>No PnL breakdown yet.</EmptyState>
      ) : (
        <>
          <div className="h-56">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
                <CartesianGrid stroke={GRID_STROKE} vertical={false} />
                <XAxis dataKey="bucket" tick={{ ...AXIS_TICK, fontSize: 11 }} />
                <YAxis
                  tick={AXIS_TICK}
                  width={70}
                  tickFormatter={(v: number) => formatVnd(v, { compact: true })}
                />
                <Tooltip
                  contentStyle={TOOLTIP_STYLE}
                  formatter={(v: number) => formatVnd(v)}
                />
                <Bar dataKey="value">
                  {data.map((d) => (
                    <Cell
                      key={d.bucket}
                      fill={(d.value ?? 0) >= 0 ? CHART_COLORS.up : CHART_COLORS.down}
                    />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
          <StaleNote asOf={asOf} stale={stale} />
        </>
      )}
    </Card>
  );
}
