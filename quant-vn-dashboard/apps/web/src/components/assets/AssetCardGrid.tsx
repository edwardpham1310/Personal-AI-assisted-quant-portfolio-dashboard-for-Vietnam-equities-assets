"use client";

import { KpiCard } from "@/components/ui/KpiCard";
import { formatVnd } from "@/lib/format";
import type { AssetsSummary } from "@/hooks/portfolio-types";

const EMPTY_SUMMARY: AssetsSummary = {
  settled_cash: 0,
  pending_cash: 0,
  advanced_cash: 0,
  cash_advance_liability: 0,
  stock_market_value: 0,
  total_equity: 0,
  available_buying_power: 0,
  withdrawable_cash: 0,
  currency: "VND",
  as_of: null,
};

/**
 * Eight-tile KPI grid for the Assets & PnL page. Renders zeros while data is
 * loading or missing so the layout is stable on first paint.
 */
export function AssetCardGrid({
  summary,
  loading,
}: {
  summary: AssetsSummary | null;
  loading?: boolean;
}) {
  const s = summary ?? EMPTY_SUMMARY;

  return (
    <div
      className="grid grid-cols-2 gap-3 md:grid-cols-4 xl:grid-cols-4"
      data-testid="asset-card-grid"
    >
      <KpiCard
        label="Settled cash"
        value={formatVnd(s.settled_cash, { compact: true })}
        hint="Available, T-settled"
        loading={loading}
      />
      <KpiCard
        label="Pending cash"
        value={formatVnd(s.pending_cash, { compact: true })}
        hint="Sale proceeds settling T+1/T+2"
        loading={loading}
      />
      <KpiCard
        label="Advanced cash"
        value={formatVnd(s.advanced_cash, { compact: true })}
        hint="Drawn against pending settlement"
        loading={loading}
      />
      <KpiCard
        label="Cash advance liability"
        value={formatVnd(s.cash_advance_liability, { compact: true })}
        hint="Fee/interest owed to broker"
        tone={s.cash_advance_liability > 0 ? "down" : "neutral"}
        loading={loading}
      />
      <KpiCard
        label="Stock market value"
        value={formatVnd(s.stock_market_value, { compact: true })}
        hint="Sum of marked positions"
        loading={loading}
      />
      <KpiCard
        label="Total equity"
        value={formatVnd(s.total_equity, { compact: true })}
        hint="Cash + stock − liability"
        loading={loading}
      />
      <KpiCard
        label="Buying power"
        value={formatVnd(s.available_buying_power, { compact: true })}
        hint="Settled + advance headroom"
        loading={loading}
      />
      <KpiCard
        label="Withdrawable"
        value={formatVnd(s.withdrawable_cash, { compact: true })}
        hint="Cash you can pull out today"
        loading={loading}
      />
    </div>
  );
}
