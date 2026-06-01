"use client";

import { Badge } from "@/components/ui/Badge";
import { ErrorState } from "@/components/ui/AsyncStates";
import { LiveQuotesPanel } from "@/components/live/LiveQuotesPanel";
import { KpiGrid } from "@/components/dashboard/KpiGrid";
import { EquityCurveChart } from "@/components/dashboard/EquityCurveChart";
import { IndexComparisonChart } from "@/components/dashboard/IndexComparisonChart";
import { AllocationDonut } from "@/components/dashboard/AllocationDonut";
import { PnlWaterfall } from "@/components/dashboard/PnlWaterfall";
import { ActionPanels } from "@/components/dashboard/ActionPanels";
import { usePortfolioMockSummary } from "@/hooks/usePortfolioMockSummary";

const DEFAULT_LIVE_SYMBOLS = ["FPT", "MWG", "HPG", "VNM", "VCB"];

export default function DashboardHomePage() {
  const portfolio = usePortfolioMockSummary();
  const updatedAt = new Date().toLocaleTimeString();

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
          {portfolio.isMock ? <Badge tone="mock">Mock Data</Badge> : null}
        </div>
      </header>

      {portfolio.error ? (
        <ErrorState
          message={`Portfolio summary error: ${portfolio.error}. Showing mock data.`}
          onRetry={portfolio.refetch}
        />
      ) : null}

      <KpiGrid summary={portfolio.data} loading={portfolio.isLoading} />

      <LiveQuotesPanel symbols={DEFAULT_LIVE_SYMBOLS} />

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <EquityCurveChart />
        <IndexComparisonChart />
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <AllocationDonut />
        <PnlWaterfall />
      </div>

      <section>
        <h2 className="text-sm font-semibold text-ink mb-2">Action panels</h2>
        <ActionPanels />
      </section>
    </div>
  );
}
