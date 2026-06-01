"use client";

import { KpiCard } from "@/components/ui/KpiCard";
import type { PortfolioSummary } from "@/lib/mock/portfolio";
import { formatPct, formatVnd, signedColor } from "@/lib/format";

export function KpiGrid({ summary, loading }: { summary: PortfolioSummary; loading: boolean }) {
  const regimeTone = summary.market_regime.toLowerCase().includes("bull")
    ? "up"
    : summary.market_regime.toLowerCase().includes("bear")
      ? "down"
      : "neutral";

  return (
    <div className="grid grid-cols-2 gap-3 md:grid-cols-4 xl:grid-cols-8">
      <KpiCard
        label="Total Equity"
        value={formatVnd(summary.total_equity_vnd, { compact: true })}
        hint="settled + pending + MtM"
        loading={loading}
      />
      <KpiCard
        label="Net PnL"
        value={formatVnd(summary.net_pnl_vnd, { compact: true })}
        tone={signedColor(summary.net_pnl_vnd)}
        loading={loading}
      />
      <KpiCard
        label="Net PnL %"
        value={formatPct(summary.net_pnl_pct)}
        tone={signedColor(summary.net_pnl_pct)}
        loading={loading}
      />
      <KpiCard
        label="Today PnL"
        value={formatVnd(summary.today_pnl_vnd, { compact: true })}
        tone={signedColor(summary.today_pnl_vnd)}
        loading={loading}
      />
      <KpiCard
        label="Available Cash"
        value={formatVnd(summary.available_cash_vnd, { compact: true })}
        hint="settled, ready to invest"
        loading={loading}
      />
      <KpiCard
        label="Pending Cash T+2"
        value={formatVnd(summary.pending_cash_vnd, { compact: true })}
        hint="settles in ≤2 trading days"
        loading={loading}
      />
      <KpiCard
        label="Risk Score"
        value={formatPct(summary.risk_score, 0)}
        hint="composite, 0 = calm, 1 = elevated"
        tone={summary.risk_score > 0.7 ? "down" : summary.risk_score < 0.3 ? "up" : "neutral"}
        loading={loading}
      />
      <KpiCard
        label="Market Regime"
        value={summary.market_regime}
        hint="heuristic, 30D trend + vol"
        tone={regimeTone as "up" | "down" | "neutral"}
        loading={loading}
      />
    </div>
  );
}
