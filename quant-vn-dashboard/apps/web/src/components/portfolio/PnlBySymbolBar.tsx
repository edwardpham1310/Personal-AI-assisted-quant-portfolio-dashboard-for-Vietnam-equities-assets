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
import type { EnrichedPosition } from "@/hooks/portfolio-types";

type Bucket = { symbol: string; value: number };

/**
 * Bar chart of unrealized PnL contribution per symbol. Green for positive,
 * red for negative. Skips positions whose PnL hasn't been marked yet.
 */
export function PnlBySymbolBar({ positions }: { positions: EnrichedPosition[] }) {
  const data = useMemo<Bucket[]>(() => {
    return positions
      .filter((p) => p.unrealized_pnl != null)
      .map((p) => ({ symbol: p.symbol, value: p.unrealized_pnl as number }))
      .sort((a, b) => b.value - a.value);
  }, [positions]);

  return (
    <Card title="Unrealized PnL by symbol" hint="Mark-to-market contribution">
      {data.length === 0 ? (
        <EmptyState>No marked positions yet.</EmptyState>
      ) : (
        <div className="h-64" data-testid="pnl-by-symbol-bar">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
              <CartesianGrid stroke="#21262d" vertical={false} />
              <XAxis
                dataKey="symbol"
                tick={{ fill: "#8b949e", fontSize: 11 }}
                interval={0}
              />
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
                  <Cell key={d.symbol} fill={d.value >= 0 ? "#22c55e" : "#ef4444"} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}
    </Card>
  );
}
