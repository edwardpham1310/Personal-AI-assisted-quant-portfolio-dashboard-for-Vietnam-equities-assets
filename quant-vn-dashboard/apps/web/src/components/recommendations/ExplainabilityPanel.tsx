"use client";

import type { RecommendationResult } from "@/hooks/useRecommendations";
import { CandlestickChart } from "@/components/market/CandlestickChart";
import { ScoreBreakdown } from "./ScoreBreakdown";

export function ReasonList({ reasons }: { reasons: string[] }) {
  if (!reasons.length) {
    return <p className="text-xs text-ink-dim">No reasons recorded.</p>;
  }
  return (
    <ul className="space-y-1 text-xs text-ink-muted">
      {reasons.map((r, i) => (
        <li key={`${r}-${i}`} className="flex items-start gap-2">
          <span className="font-mono text-[10px] text-accent">»</span>
          <span className="break-words">{r}</span>
        </li>
      ))}
    </ul>
  );
}

export function WarningList({ warnings }: { warnings: string[] }) {
  if (!warnings.length) {
    return <p className="text-xs text-ink-dim">No warnings.</p>;
  }
  return (
    <ul className="space-y-1 text-xs text-amber-400">
      {warnings.map((w, i) => (
        <li key={`${w}-${i}`} className="flex items-start gap-2">
          <span className="font-mono text-[10px]">!</span>
          <span className="break-words">{w}</span>
        </li>
      ))}
    </ul>
  );
}

export function ExplainabilityPanel({ rec }: { rec: RecommendationResult | null }) {
  if (!rec) {
    return (
      <div className="rounded border border-border bg-bg-panel p-4">
        <p className="text-xs text-ink-dim">
          Select a recommendation row to see the explainability breakdown.
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-4 rounded border border-border bg-bg-panel p-4">
      <header>
        <h3 className="text-sm font-medium text-ink">Explainability · {rec.symbol}</h3>
        <p className="text-[10px] text-ink-dim">
          research signal · not financial advice · no orders placed
        </p>
      </header>
      {/* Phase 2 data-policy: every recommended stock must include a chart
          drawer with daily candles + MA overlay + data-freshness context.
          The chart pulls real OHLCV via the backend gateway. */}
      <section>
        <h4 className="mb-2 text-xs uppercase tracking-wide text-ink-dim">Daily chart</h4>
        {/* ``key`` forces a remount when the selected symbol changes, so
            the internal ``useState(initialSymbol)`` picks up the new value. */}
        <CandlestickChart key={rec.symbol} initialSymbol={rec.symbol} />
        {rec.last_price != null ? (
          <p className="mt-2 text-[10px] text-ink-dim">
            Last quote: {rec.last_price.toLocaleString()} · as of {rec.as_of}
          </p>
        ) : null}
      </section>
      <section>
        <h4 className="mb-2 text-xs uppercase tracking-wide text-ink-dim">Scores</h4>
        <ScoreBreakdown scores={rec.scores} />
      </section>
      <section>
        <h4 className="mb-2 text-xs uppercase tracking-wide text-ink-dim">Reasons</h4>
        <ReasonList reasons={rec.reasons} />
      </section>
      <section>
        <h4 className="mb-2 text-xs uppercase tracking-wide text-ink-dim">Warnings</h4>
        <WarningList warnings={rec.warnings} />
      </section>
    </div>
  );
}
