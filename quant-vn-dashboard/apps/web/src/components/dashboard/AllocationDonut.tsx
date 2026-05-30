"use client";

import { PieChart, Pie, Cell, Tooltip, ResponsiveContainer, Legend } from "recharts";
import { Card } from "@/components/ui/Card";
import { EmptyState } from "@/components/ui/AsyncStates";
import { MOCK_ALLOCATION, type AllocationSlice } from "@/lib/mock/portfolio";
import { formatVnd } from "@/lib/format";

const COLORS = ["#4f8bf0", "#22c55e", "#a855f7", "#f59e0b", "#64748b"];

export function AllocationDonut({ data = MOCK_ALLOCATION }: { data?: AllocationSlice[] }) {
  return (
    <Card title="Allocation" hint="By sector (mock)">
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
                contentStyle={{ background: "#0b0d10", border: "1px solid #21262d", fontSize: 12 }}
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
