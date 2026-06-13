"use client";

import { PieChart, Pie, Cell, Tooltip, ResponsiveContainer, Legend } from "recharts";
import { Card } from "@/components/ui/Card";
import { EmptyState } from "@/components/ui/AsyncStates";
import type { AllocationSlice } from "@/lib/mock/portfolio";
import { formatVnd } from "@/lib/format";
import { CHART_COLORS, TOOLTIP_STYLE } from "@/lib/chart";

const COLORS = CHART_COLORS.series;

export function AllocationDonut({ data = [] }: { data?: AllocationSlice[] }) {
  return (
    <Card title="Allocation" hint="By strategy tag (market value)">
      {data.length === 0 ? (
        <EmptyState>No allocation data.</EmptyState>
      ) : (
        <div className="h-56">
          <ResponsiveContainer width="100%" height="100%">
            <PieChart>
              <Pie
                data={data}
                dataKey="value"
                nameKey="sector"
                innerRadius={50}
                outerRadius={80}
                stroke="#11151a"
                strokeWidth={2}
              >
                {data.map((_, i) => (
                  <Cell key={i} fill={COLORS[i % COLORS.length]} />
                ))}
              </Pie>
              <Tooltip
                contentStyle={TOOLTIP_STYLE}
                formatter={(v: number) => formatVnd(v)}
              />
              <Legend wrapperStyle={{ fontSize: 11 }} />
            </PieChart>
          </ResponsiveContainer>
        </div>
      )}
    </Card>
  );
}
