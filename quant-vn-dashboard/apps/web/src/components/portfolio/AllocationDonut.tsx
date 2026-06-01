"use client";

import { useMemo } from "react";
import { PieChart, Pie, Cell, Tooltip, ResponsiveContainer, Legend } from "recharts";
import { Card } from "@/components/ui/Card";
import { EmptyState } from "@/components/ui/AsyncStates";
import { formatNumber } from "@/lib/format";
import type { EnrichedPosition } from "@/hooks/portfolio-types";

const COLORS = [
  "#4f8bf0",
  "#22c55e",
  "#a855f7",
  "#f59e0b",
  "#ef4444",
  "#06b6d4",
  "#84cc16",
  "#ec4899",
];

type Slice = { name: string; value: number };

/**
 * Donut chart of portfolio allocation by symbol (using market value).
 *
 * Falls back to a friendly empty state when there are no positions or every
 * position has a null market value — the chart never crashes on empty data.
 */
export function AllocationDonut({ positions }: { positions: EnrichedPosition[] }) {
  const data = useMemo<Slice[]>(() => {
    return positions
      .map((p) => ({
        name: p.symbol,
        value: p.market_value ?? 0,
      }))
      .filter((s) => s.value > 0);
  }, [positions]);

  return (
    <Card title="Allocation by symbol" hint="Weight from market value">
      {data.length === 0 ? (
        <EmptyState>
          No allocation yet. Add positions with a recent market price to see weights.
        </EmptyState>
      ) : (
        <div className="h-64" data-testid="allocation-donut">
          <ResponsiveContainer width="100%" height="100%">
            <PieChart>
              <Pie
                data={data}
                dataKey="value"
                nameKey="name"
                innerRadius={50}
                outerRadius={80}
                stroke="#11151a"
                strokeWidth={2}
              >
                {data.map((s, i) => (
                  <Cell
                    key={s.name}
                    fill={COLORS[i % COLORS.length]}
                    data-testid={`allocation-slice-${s.name}`}
                  />
                ))}
              </Pie>
              <Tooltip
                contentStyle={{
                  background: "#0b0d10",
                  border: "1px solid #21262d",
                  fontSize: 12,
                }}
                formatter={(v: number) => `${formatNumber(v)} VND`}
              />
              <Legend wrapperStyle={{ fontSize: 11 }} />
            </PieChart>
          </ResponsiveContainer>
        </div>
      )}
    </Card>
  );
}
