"use client";

import { KpiCard } from "@/components/ui/KpiCard";
import type { AssetsSummary, PortfolioSummary } from "@/hooks/portfolio-types";
import { formatVnd, signedColor } from "@/lib/format";

const PLACEHOLDER = "—";

/**
 * Dashboard Home KPI grid, backed by the real ``GET /portfolio/summary`` and
 * ``GET /assets/summary`` endpoints.
 *
 * Three tiles (Today PnL, Risk Score, Market Regime) have no backend source
 * yet and render ``—`` with a TODO hint rather than fabricated numbers. Wire
 * them once the API exposes intraday PnL / a risk score / a regime signal.
 *
 * NOTE: ``total_unrealized_pnl_pct`` is already in *percent units* (e.g. -3.42
 * means -3.42%), so it is rendered directly — do NOT pass it through
 * ``formatPct`` (which multiplies by 100).
 */
export function KpiGrid({
  summary,
  assets,
  loading,
}: {
  summary: PortfolioSummary | null;
  assets: AssetsSummary | null;
  loading: boolean;
}) {
  const unrealizedPnl = summary?.total_unrealized_pnl ?? null;
  const unrealizedPnlPct = summary?.total_unrealized_pnl_pct ?? null;

  return (
    <div className="grid grid-cols-2 gap-3 md:grid-cols-4 xl:grid-cols-8">
      <KpiCard
        label="Total Equity"
        value={assets ? formatVnd(assets.total_equity, { compact: true }) : PLACEHOLDER}
        hint="settled + pending + MtM"
        loading={loading}
      />
      <KpiCard
        label="Unrealized PnL"
        value={unrealizedPnl != null ? formatVnd(unrealizedPnl, { compact: true }) : PLACEHOLDER}
        tone={unrealizedPnl != null ? signedColor(unrealizedPnl) : "neutral"}
        hint="open positions, mark-to-market"
        loading={loading}
      />
      <KpiCard
        label="Unrealized PnL %"
        value={
          unrealizedPnlPct != null
            ? `${unrealizedPnlPct >= 0 ? "+" : ""}${unrealizedPnlPct.toFixed(2)}%`
            : PLACEHOLDER
        }
        tone={unrealizedPnlPct != null ? signedColor(unrealizedPnlPct) : "neutral"}
        hint="vs. cost basis"
        loading={loading}
      />
      <KpiCard
        label="Available Cash"
        value={assets ? formatVnd(assets.settled_cash, { compact: true }) : PLACEHOLDER}
        hint="settled, ready to invest"
        loading={loading}
      />
      <KpiCard
        label="Pending Cash T+2"
        value={assets ? formatVnd(assets.pending_cash, { compact: true }) : PLACEHOLDER}
        hint="settles in ≤2 trading days"
        loading={loading}
      />
      <KpiCard label="Today PnL" value={PLACEHOLDER} hint="TODO: no backend endpoint yet" />
      <KpiCard label="Risk Score" value={PLACEHOLDER} hint="TODO: no backend endpoint yet" />
      <KpiCard label="Market Regime" value={PLACEHOLDER} hint="TODO: no backend endpoint yet" />
    </div>
  );
}
