"use client";

import { ErrorState } from "@/components/ui/AsyncStates";
import { LiveQuotesPanel } from "@/components/live/LiveQuotesPanel";
import { KpiGrid } from "@/components/dashboard/KpiGrid";
import { EquityCurveChart } from "@/components/dashboard/EquityCurveChart";
import { IndexComparisonChart } from "@/components/dashboard/IndexComparisonChart";
import { AllocationDonut } from "@/components/dashboard/AllocationDonut";
import { PnlWaterfall } from "@/components/dashboard/PnlWaterfall";
import { ActionPanels } from "@/components/dashboard/ActionPanels";
import { usePortfolioSummary } from "@/hooks/usePortfolioSummary";
import { useAssetsSummary } from "@/hooks/useAssetsSummary";
import { isProductionBuild } from "@/lib/env";

const DEFAULT_LIVE_SYMBOLS = ["FPT", "MWG", "HPG", "VNM", "VCB"];

// These four charts have no backend endpoint yet. In production we pass an
// empty series so they render an honest empty state instead of mock data; in
// development the components fall back to their mock default prop for UI work.
const PROD_EMPTY = isProductionBuild ? [] : undefined;

export default function DashboardHomePage() {
  const portfolio = usePortfolioSummary();
  const assets = useAssetsSummary();
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

      <KpiGrid summary={portfolio.summary} assets={assets.summary} loading={loading} />

      <LiveQuotesPanel symbols={DEFAULT_LIVE_SYMBOLS} />

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <EquityCurveChart data={PROD_EMPTY} />
        <IndexComparisonChart data={PROD_EMPTY} />
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <AllocationDonut data={PROD_EMPTY} />
        <PnlWaterfall data={PROD_EMPTY} />
      </div>

      <section>
        <h2 className="text-sm font-semibold text-ink mb-2">Action panels</h2>
        <ActionPanels />
      </section>
    </div>
  );
}
