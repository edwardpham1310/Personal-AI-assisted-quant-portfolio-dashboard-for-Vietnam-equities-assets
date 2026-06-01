"use client";

import { useMemo } from "react";
import { PieChart, Pie, Cell, Tooltip, ResponsiveContainer, Legend } from "recharts";
import { Card } from "@/components/ui/Card";
import { EmptyState } from "@/components/ui/AsyncStates";
import { formatNumber } from "@/lib/format";
import type { PortfolioSummary } from "@/hooks/portfolio-types";

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
 * Donut chart of allocation grouped by strategy tag — driven by the
 * ``by_strategy_tag`` map from ``PortfolioSummary``.
 */
export function StrategyAllocationDonut({ summary }: { summary: PortfolioSummary | null }) {
  const data = useMemo<Slice[]>(() => {
    if (!summary) return [];
    return Object.entries(summary.by_strategy_tag)
      .map(([name, bucket]) => ({
        name: name || "untagged",
        value: bucket.market_value,
      }))
      .filter((s) => s.value > 0);
  }, [summary]);

  return (
    <Card title="Allocation by strategy" hint="Grouped by strategy_tag">
      {data.length === 0 ? (
        <EmptyState>No strategy buckets yet.</EmptyState>
      ) : (
        <div className="h-64" data-testid="strategy-allocation-donut">
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
                  <Cell key={s.name} fill={COLORS[i % COLORS.length]} />
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
