"use client";

import { useMemo } from "react";
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
import { formatVnd } from "@/lib/format";
import type { AssetsPnl } from "@/hooks/portfolio-types";

type Row = { name: string; value: number };

export function RealizedVsUnrealizedChart({ pnl }: { pnl: AssetsPnl | null }) {
  const data = useMemo<Row[]>(() => {
    if (!pnl) return [];
    return [
      { name: "Realized", value: pnl.realized },
      { name: "Unrealized", value: pnl.unrealized },
    ];
  }, [pnl]);

  return (
    <Card
      title="Realized vs Unrealized PnL"
      hint={pnl ? `Total ${formatVnd(pnl.total, { compact: true })}` : "Awaiting data"}
    >
      {data.length === 0 ? (
        <EmptyState>No PnL data yet.</EmptyState>
      ) : (
        <div className="h-56" data-testid="realized-vs-unrealized-chart">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
              <CartesianGrid stroke="#21262d" vertical={false} />
              <XAxis dataKey="name" tick={{ fill: "#8b949e", fontSize: 11 }} />
              <YAxis
                tick={{ fill: "#8b949e", fontSize: 10 }}
                width={70}
                tickFormatter={(v: number) => formatVnd(v, { compact: true })}
              />
              <Tooltip
                contentStyle={{
                  background: "#0b0d10",
                  border: "1px solid #21262d",
                  fontSize: 12,
                }}
                formatter={(v: number) => formatVnd(v)}
              />
              <Bar dataKey="value">
                {data.map((d) => (
                  <Cell key={d.name} fill={d.value >= 0 ? "#22c55e" : "#ef4444"} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}
    </Card>
  );
}
