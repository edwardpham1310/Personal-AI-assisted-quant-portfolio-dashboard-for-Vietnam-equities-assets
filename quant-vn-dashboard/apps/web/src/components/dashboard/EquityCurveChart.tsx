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
import { MOCK_EQUITY_CURVE, type EquityPoint } from "@/lib/mock/portfolio";
import { formatVnd } from "@/lib/format";

export function EquityCurveChart({ data = MOCK_EQUITY_CURVE }: { data?: EquityPoint[] }) {
  return (
    <Card title="Portfolio equity curve" hint="Mock daily series — 90 trading days">
      {data.length === 0 ? (
        <EmptyState>No portfolio history yet.</EmptyState>
      ) : (
        <div className="h-56">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
              <CartesianGrid stroke="#21262d" vertical={false} />
              <XAxis dataKey="ts" tick={{ fill: "#8b949e", fontSize: 10 }} minTickGap={32} />
              <YAxis
                tick={{ fill: "#8b949e", fontSize: 10 }}
                width={70}
                tickFormatter={(v: number) => formatVnd(v, { compact: true })}
              />
              <Tooltip
                contentStyle={{ background: "#0b0d10", border: "1px solid #21262d", fontSize: 12 }}
                labelStyle={{ color: "#e6edf3" }}
                formatter={(v: number) => formatVnd(v)}
              />
              <Line type="monotone" dataKey="equity" stroke="#4f8bf0" strokeWidth={2} dot={false} />
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}
    </Card>
  );
}
