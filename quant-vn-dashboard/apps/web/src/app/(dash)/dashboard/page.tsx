"use client";

import { ErrorState } from "@/components/ui/AsyncStates";
import { LiveQuotesPanel } from "@/components/live/LiveQuotesPanel";
import { KpiGrid } from "@/components/dashboard/KpiGrid";
import { EquityCurveChart } from "@/components/dashboard/EquityCurveChart";
import { IndexComparisonChart } from "@/components/dashboard/IndexComparisonChart";
import { AllocationDonut } from "@/components/dashboard/AllocationDonut";
import { PnlWaterfall } from "@/components/dashboard/PnlWaterfall";
import { RiskScoreCard } from "@/components/dashboard/RiskScoreCard";
import { ActionPanels } from "@/components/dashboard/ActionPanels";
import { usePortfolioSummary } from "@/hooks/usePortfolioSummary";
import { usePortfolioRiskScore } from "@/hooks/usePortfolioRiskScore";
import { useAssetsSummary } from "@/hooks/useAssetsSummary";
import { usePortfolioTodayPnl } from "@/hooks/usePortfolioTodayPnl";
import { useMarketRegime } from "@/hooks/useMarketRegime";
import { usePortfolioAllocation } from "@/hooks/usePortfolioAllocation";
import { useEquityCurve } from "@/hooks/useEquityCurve";
import { usePnlWaterfall } from "@/hooks/usePnlWaterfall";
import { RangeSelect } from "@/components/ui/RangeSelect";
import { EQUITY_RANGE_OPTIONS, type RangeKey } from "@/lib/dateRange";
import { useState } from "react";
import { isProductionBuild } from "@/lib/env";

const DEFAULT_LIVE_SYMBOLS = ["FPT", "MWG", "HPG", "VNM", "VCB"];

// Equity-curve and PnL-waterfall are now backed by real endpoints. When the
// backend returns data we show it. When it returns honest-empty ([]), in
// production we keep the empty array (honest empty state, never mock); in
// development we pass `undefined` so the components fall back to their mock
// default prop for local design work.
const PROD_EMPTY = isProductionBuild ? [] : undefined;
function liveOrEmpty<T>(rows: T[]): T[] | undefined {
  return rows.length > 0 ? rows : PROD_EMPTY;
}

export default function DashboardHomePage() {
  const portfolio = usePortfolioSummary();
  const assets = useAssetsSummary();
  const todayPnl = usePortfolioTodayPnl();
  const regime = useMarketRegime();
  const allocation = usePortfolioAllocation();
  const [equityRange, setEquityRange] = useState<RangeKey>("3M");
  const equityCurve = useEquityCurve(equityRange);
  const pnlWaterfall = usePnlWaterfall();
  const risk = usePortfolioRiskScore();
  const updatedAt = new Date().toLocaleTimeString();
  const loading = portfolio.loading || assets.loading;
  const error = portfolio.error ?? assets.error;

  return (
    <div className="space-y-6">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold text-ink">Dashboard Home</h1>
          <p className="text-sm text-ink-dim mt-1">
            Portfolio summary, market context, and recommendation surface.
            <span className="ml-2 text-ink-dim">
              Phase 1 is <span className="text-ink">recommend-only</span> — no orders are placed.
            </span>
          </p>
        </div>
        <div className="flex items-center gap-2 text-xs text-ink-dim">
          <span>Updated {updatedAt}</span>
        </div>
      </header>

      {error ? (
        <ErrorState
          message={`Portfolio summary error: ${error}`}
          onRetry={() => {
            void portfolio.refresh();
            void assets.refresh();
          }}
        />
      ) : null}

      <KpiGrid
        summary={portfolio.summary}
        assets={assets.summary}
        loading={loading}
        todayPnl={todayPnl.data?.total_day_pnl ?? null}
        regime={regime.data?.label ?? null}
        riskScore={risk.data?.score ?? null}
        riskBand={risk.data?.band ?? null}
      />

      <LiveQuotesPanel symbols={DEFAULT_LIVE_SYMBOLS} />

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <EquityCurveChart
          data={liveOrEmpty(equityCurve.data)}
          action={
            <RangeSelect
              value={equityRange}
              options={EQUITY_RANGE_OPTIONS}
              onChange={setEquityRange}
            />
          }
        />
        <IndexComparisonChart />
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <AllocationDonut data={allocation.data} />
        <PnlWaterfall data={liveOrEmpty(pnlWaterfall.data)} />
      </div>

      <RiskScoreCard />

      <section>
        <h2 className="text-sm font-semibold text-ink mb-2">Action panels</h2>
        <ActionPanels />
      </section>
    </div>
  );
}
