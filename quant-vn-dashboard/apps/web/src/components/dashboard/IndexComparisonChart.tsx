"use client";

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
import { makeMockIndexComparison } from "@/lib/mock/market";

const DATA = makeMockIndexComparison(90);

export function IndexComparisonChart() {
  return (
    <Card title="VNINDEX vs VN30" hint="90D rebased to 100">
      <div className="h-56">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={DATA} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
            <CartesianGrid stroke="#21262d" vertical={false} />
            <XAxis dataKey="ts" tick={{ fill: "#8b949e", fontSize: 10 }} minTickGap={32} />
            <YAxis tick={{ fill: "#8b949e", fontSize: 10 }} width={48} />
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
    </Card>
  );
}
