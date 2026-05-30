"use client";

import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
} from "recharts";
import { Card } from "@/components/ui/Card";
import { EmptyState } from "@/components/ui/AsyncStates";
import { formatVnd } from "@/lib/format";
import type { CostBreakdown, CostPeriod } from "@/hooks/portfolio-types";

const PERIODS: CostPeriod[] = ["MTD", "YTD", "ALL"];

const COLORS = {
  brokerage_fee: "#4f8bf0",
  vat: "#a855f7",
  sell_tax: "#ef4444",
  cash_advance_fee: "#f59e0b",
  slippage_estimate: "#06b6d4",
} as const;

const LABELS = {
  brokerage_fee: "Brokerage",
  vat: "VAT",
  sell_tax: "Sell tax",
  cash_advance_fee: "Cash advance",
  slippage_estimate: "Slippage",
} as const;

/**
 * Stacked bar of fee + tax drag for the selected period. We render a single
 * stacked bar (one X tick = the selected period) so each cost layer is easy
 * to compare visually.
 */
export function FeeTaxDragChart({
  costs,
  period,
  onPeriodChange,
}: {
  costs: CostBreakdown | null;
  period: CostPeriod;
  onPeriodChange: (next: CostPeriod) => void;
}) {
  const hasData =
    costs != null &&
    (costs.brokerage_fee !== 0 ||
      costs.vat !== 0 ||
      costs.sell_tax !== 0 ||
      costs.cash_advance_fee !== 0 ||
      costs.slippage_estimate !== 0);

  const data = costs
    ? [
        {
          period: costs.period,
          brokerage_fee: costs.brokerage_fee,
          vat: costs.vat,
          sell_tax: costs.sell_tax,
          cash_advance_fee: costs.cash_advance_fee,
          slippage_estimate: costs.slippage_estimate,
        },
      ]
    : [];

  return (
    <Card
      title="Fee + tax drag"
      hint={
        costs
          ? `Total ${formatVnd(costs.total, { compact: true })} (${costs.period})`
          : "Brokerage + VAT + sell tax + advance fee + slippage estimate"
      }
    >
      <div className="mb-3 flex items-center gap-2" role="tablist" aria-label="Cost period">
        {PERIODS.map((p) => {
          const active = p === period;
          return (
            <button
              key={p}
              type="button"
              role="tab"
              aria-selected={active}
              onClick={() => onPeriodChange(p)}
              className={`rounded border px-2 py-0.5 text-xs ${
                active
                  ? "border-accent bg-accent/15 text-accent"
                  : "border-border bg-bg-subtle text-ink-muted hover:border-accent"
              }`}
            >
              {p}
            </button>
          );
        })}
      </div>

      {!hasData ? (
        <EmptyState>No costs recorded for this period.</EmptyState>
      ) : (
        <div className="h-56" data-testid="fee-tax-drag-chart">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
              <CartesianGrid stroke="#21262d" vertical={false} />
              <XAxis dataKey="period" tick={{ fill: "#8b949e", fontSize: 11 }} />
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
              <Legend wrapperStyle={{ fontSize: 11 }} />
              {(Object.keys(LABELS) as (keyof typeof LABELS)[]).map((key) => (
                <Bar
                  key={key}
                  dataKey={key}
                  stackId="costs"
                  name={LABELS[key]}
                  fill={COLORS[key]}
                />
              ))}
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}
    </Card>
  );
}
