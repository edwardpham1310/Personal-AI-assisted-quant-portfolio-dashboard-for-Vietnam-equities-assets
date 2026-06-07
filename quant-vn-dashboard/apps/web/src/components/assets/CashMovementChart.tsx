"use client";

import { useState } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { Card } from "@/components/ui/Card";
import { EmptyState } from "@/components/ui/AsyncStates";
import { Skeleton } from "@/components/ui/Skeleton";
import { RangeSelect } from "@/components/ui/RangeSelect";
import { useAssetsCashMovements } from "@/hooks/useAssetsCashMovements";
import { EQUITY_RANGE_OPTIONS, type RangeKey } from "@/lib/dateRange";
import { formatVnd } from "@/lib/format";

/**
 * Trade-driven cash flows over time (− buys, + sells), ascending L→R. Real data
 * only; deposits/withdrawals are not tracked (shown in the hint). Honest-empty
 * until trades exist.
 */
export function CashMovementChart() {
  const [range, setRange] = useState<RangeKey>("3M");
  const { data, loading, error } = useAssetsCashMovements(range);
  const movements = data?.movements ?? [];

  return (
    <Card
      title="Cash movement"
      hint="Trade-driven flows — deposits/withdrawals not tracked"
      action={<RangeSelect value={range} options={EQUITY_RANGE_OPTIONS} onChange={setRange} />}
    >
      {loading && !data ? (
        <Skeleton height={224} />
      ) : error ? (
        <p className="text-xs text-accent-down">{error}</p>
      ) : movements.length === 0 ? (
        <EmptyState>No cash movements in this range.</EmptyState>
      ) : (
        <>
          <div className="h-48">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={movements} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
                <CartesianGrid stroke="#21262d" vertical={false} />
                <XAxis dataKey="date" tick={{ fill: "#8b949e", fontSize: 10 }} minTickGap={24} />
                <YAxis
                  tick={{ fill: "#8b949e", fontSize: 10 }}
                  width={64}
                  tickFormatter={(v: number) => formatVnd(v, { compact: true })}
                />
                <Tooltip
                  contentStyle={{ background: "#0b0d10", border: "1px solid #21262d", fontSize: 12 }}
                  formatter={(v: number) => formatVnd(v)}
                />
                <Bar dataKey="amount">
                  {movements.map((m, i) => (
                    <Cell key={`${m.date}-${i}`} fill={m.amount >= 0 ? "#22c55e" : "#ef4444"} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
          <p className="mt-2 text-[11px] text-ink-dim">
            Net flow:{" "}
            <span className={(data?.net_cash_flow ?? 0) >= 0 ? "text-accent-up" : "text-accent-down"}>
              {formatVnd(data?.net_cash_flow ?? 0)}
            </span>
          </p>
        </>
      )}
    </Card>
  );
}
