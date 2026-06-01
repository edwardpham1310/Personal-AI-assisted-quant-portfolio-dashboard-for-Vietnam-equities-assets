"use client";

import { Badge } from "@/components/ui/Badge";
import { ErrorState } from "@/components/ui/AsyncStates";
import { CandlestickChart } from "@/components/market/CandlestickChart";
import { IndexCardGrid } from "@/components/market/IndexCardGrid";
import { MarketBreadthCard } from "@/components/market/MarketBreadthCard";
import { TopMoversCard } from "@/components/market/TopMoversCard";
import { useMarketIndices } from "@/hooks/useMarketIndices";
import { useMarketBreadth } from "@/hooks/useMarketBreadth";
import { useTopMovers } from "@/hooks/useTopMovers";

export default function MarketOverviewPage() {
  const indices = useMarketIndices();
  const breadth = useMarketBreadth();
  const movers = useTopMovers();
  const updatedAt = new Date().toLocaleTimeString();
  const anyMock = indices.isMock || breadth.isMock || movers.isMock;

  return (
    <div className="space-y-6">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold text-ink">Market Overview</h1>
          <p className="text-sm text-ink-dim mt-1">
            VN indices, breadth, top movers, and an interactive candlestick. Data sourced from the
            FastAPI gateway — never from SSI directly.
          </p>
        </div>
        <div className="flex items-center gap-2 text-xs text-ink-dim">
          <span>Updated {updatedAt}</span>
          {anyMock ? <Badge tone="mock">Mock Data</Badge> : null}
        </div>
      </header>

      {indices.error ? (
        <ErrorState
          message={`Indices error: ${indices.error}. Showing mock data.`}
          onRetry={indices.refetch}
        />
      ) : null}

      {breadth.error ? (
        <ErrorState message={`Market breadth error: ${breadth.error}.`} onRetry={breadth.refetch} />
      ) : null}

      {movers.error ? (
        <ErrorState message={`Top movers error: ${movers.error}.`} onRetry={movers.refetch} />
      ) : null}

      <IndexCardGrid indices={indices.data} loading={indices.isLoading} />

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <MarketBreadthCard breadth={breadth.data} isMock={breadth.isMock} />
        <TopMoversCard movers={movers.data} isMock={movers.isMock} />
      </div>

      <CandlestickChart initialSymbol="FPT" />
    </div>
  );
}
