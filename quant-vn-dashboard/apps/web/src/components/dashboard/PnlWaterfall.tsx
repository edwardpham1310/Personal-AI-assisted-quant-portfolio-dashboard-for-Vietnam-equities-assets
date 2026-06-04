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
import { MOCK_PNL_BUCKETS, type PnlBucket } from "@/lib/mock/portfolio";
import { formatVnd } from "@/lib/format";

export function PnlWaterfall({ data = MOCK_PNL_BUCKETS }: { data?: PnlBucket[] }) {
  return (
    <Card title="PnL by bucket" hint="Realized + unrealized − costs → net contribution">
      {data.length === 0 ? (
        <EmptyState>No PnL breakdown yet.</EmptyState>
      ) : (
        <div className="h-56">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
              <CartesianGrid stroke="#21262d" vertical={false} />
              <XAxis dataKey="bucket" tick={{ fill: "#8b949e", fontSize: 11 }} />
              <YAxis
                tick={{ fill: "#8b949e", fontSize: 10 }}
                width={70}
                tickFormatter={(v: number) => formatVnd(v, { compact: true })}
              />
              <Tooltip
                contentStyle={{ background: "#0b0d10", border: "1px solid #21262d", fontSize: 12 }}
                formatter={(v: number) => formatVnd(v)}
              />
              <Bar dataKey="value">
                {data.map((d) => (
                  <Cell key={d.bucket} fill={d.value >= 0 ? "#22c55e" : "#ef4444"} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}
    </Card>
  );
}
