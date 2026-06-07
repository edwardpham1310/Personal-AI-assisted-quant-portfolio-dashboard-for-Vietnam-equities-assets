"use client";

import { Card } from "@/components/ui/Card";
import { EmptyState } from "@/components/ui/AsyncStates";
import { Skeleton } from "@/components/ui/Skeleton";
import { usePortfolioRiskScore, type RiskComponent } from "@/hooks/usePortfolioRiskScore";

const BAND_TONE: Record<string, string> = {
  low: "text-accent-up",
  moderate: "text-ink",
  elevated: "text-accent-down",
  high: "text-accent-down",
  unavailable: "text-ink-dim",
};

function ComponentRow({ c }: { c: RiskComponent }) {
  if (!c.available) {
    return (
      <div className="flex items-center justify-between border-t border-border py-1.5 text-xs">
        <span className="text-ink-muted">{c.label}</span>
        <span className="text-ink-dim" title={c.reason ?? undefined}>
          unavailable{c.reason ? ` · ${c.reason.replace(/_/g, " ")}` : ""}
        </span>
      </div>
    );
  }
  const score = c.score ?? 0;
  const tone = score >= 75 ? "text-accent-down" : score >= 50 ? "text-ink" : "text-accent-up";
  return (
    <div className="border-t border-border py-1.5 text-xs">
      <div className="flex items-center justify-between">
        <span className="text-ink">{c.label}</span>
        <span className={`font-mono ${tone}`}>{Math.round(score)}</span>
      </div>
      {c.detail ? <p className="mt-0.5 text-[11px] text-ink-dim">{c.detail}</p> : null}
    </div>
  );
}

/**
 * Read-only portfolio risk score + explainable component breakdown. Honest
 * partial/empty states: shows the overall score only when at least one
 * component is available, and lists each component's availability + reason.
 * Never fabricates a number.
 */
export function RiskScoreCard() {
  const { data, loading, error } = usePortfolioRiskScore();

  const hint = "Read-only analytics · 0–100 (higher = riskier) · research only";

  if (loading && !data) {
    return (
      <Card title="Portfolio risk score" hint={hint}>
        <Skeleton height={160} />
      </Card>
    );
  }
  if (error || !data) {
    return (
      <Card title="Portfolio risk score" hint={hint}>
        <p className="text-xs text-ink-dim">Risk score unavailable right now.</p>
      </Card>
    );
  }

  const bandTone = BAND_TONE[data.band] ?? "text-ink";

  return (
    <Card title="Portfolio risk score" hint={hint}>
      {data.score == null ? (
        <EmptyState>
          Not enough data yet — add positions to compute a risk score.
        </EmptyState>
      ) : (
        <div className="mb-2 flex items-baseline gap-2">
          <span className={`font-mono text-3xl ${bandTone}`}>{Math.round(data.score)}</span>
          <span className={`text-sm capitalize ${bandTone}`}>{data.band}</span>
          <span className="ml-auto text-[11px] text-ink-dim">
            {data.available_count}/{data.total_count} components
          </span>
        </div>
      )}
      <div>
        {data.components.map((c) => (
          <ComponentRow key={c.key} c={c} />
        ))}
      </div>
    </Card>
  );
}
