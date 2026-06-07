"use client";

import { useState } from "react";
import { ErrorState } from "@/components/ui/AsyncStates";
import { useAssetsSummary } from "@/hooks/useAssetsSummary";
import { useAssetsPnl } from "@/hooks/useAssetsPnl";
import { useAssetsCosts } from "@/hooks/useAssetsCosts";
import { AssetCardGrid } from "@/components/assets/AssetCardGrid";
import { RealizedVsUnrealizedChart } from "@/components/assets/RealizedVsUnrealizedChart";
import { FeeTaxDragChart } from "@/components/assets/FeeTaxDragChart";
import { CashMovementChart } from "@/components/assets/CashMovementChart";
import { SettlementAlertsCard } from "@/components/assets/SettlementAlertsCard";
import { EquityCurveChart } from "@/components/dashboard/EquityCurveChart";
import { RangeSelect } from "@/components/ui/RangeSelect";
import { useEquityCurve } from "@/hooks/useEquityCurve";
import { EQUITY_RANGE_OPTIONS, type RangeKey } from "@/lib/dateRange";
import { isProductionBuild } from "@/lib/env";
import type { CostPeriod } from "@/hooks/portfolio-types";

// Net worth ≡ NAV history (real equity-curve snapshots). In production an empty
// curve stays empty (honest); in dev pass undefined so the chart shows its mock
// default for design work — never mock in production.
const PROD_EMPTY = isProductionBuild ? [] : undefined;

export default function AssetsPnlPage() {
  const assets = useAssetsSummary();
  const pnl = useAssetsPnl();
  const [period, setPeriod] = useState<CostPeriod>("MTD");
  const costs = useAssetsCosts(period);
  const [netWorthRange, setNetWorthRange] = useState<RangeKey>("3M");
  const netWorth = useEquityCurve(netWorthRange);

  const anyLoading = assets.loading || pnl.loading || costs.loading;
  const refresh = () => {
    void assets.refresh();
    void pnl.refresh();
    void costs.refresh();
  };

  return (
    <div className="space-y-6">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold text-ink">Assets & PnL</h1>
          <p className="text-sm text-ink-dim mt-1">
            Cash, settlement, equity, and realized + unrealized PnL with T+2 awareness.
          </p>
          <p className="text-[11px] text-ink-dim mt-2">
            Research dashboard · Manual entry · No orders placed.
          </p>
        </div>
        <button
          type="button"
          onClick={refresh}
          disabled={anyLoading}
          className="rounded border border-border bg-bg-subtle px-2 py-1 text-xs text-ink hover:border-accent disabled:opacity-50"
        >
          {anyLoading ? "Refreshing…" : "Refresh"}
        </button>
      </header>

      {assets.error ? (
        <ErrorState
          message={`Assets summary error: ${assets.error}`}
          onRetry={() => void assets.refresh()}
        />
      ) : null}

      <AssetCardGrid summary={assets.summary} loading={assets.loading} />

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        {pnl.error ? (
          <ErrorState message={`PnL error: ${pnl.error}`} onRetry={() => void pnl.refresh()} />
        ) : (
          <RealizedVsUnrealizedChart pnl={pnl.pnl} />
        )}
        {costs.error ? (
          <ErrorState
            message={`Costs error: ${costs.error}`}
            onRetry={() => void costs.refresh()}
          />
        ) : (
          <FeeTaxDragChart costs={costs.costs} period={period} onPeriodChange={setPeriod} />
        )}
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <EquityCurveChart
          title="Net-worth curve"
          data={netWorth.data.length > 0 ? netWorth.data : PROD_EMPTY}
          action={
            <RangeSelect
              value={netWorthRange}
              options={EQUITY_RANGE_OPTIONS}
              onChange={setNetWorthRange}
            />
          }
        />
        <CashMovementChart />
      </div>

      <SettlementAlertsCard />
    </div>
  );
}
