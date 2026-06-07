"use client";

import {
  useRecommendationExplanation,
  type RecommendationResult,
  type ScoreContribution,
} from "@/hooks/useRecommendations";
import { CandlestickChart } from "@/components/market/CandlestickChart";
import { ScoreBreakdown } from "./ScoreBreakdown";

function ContributionBreakdown({ rows }: { rows: ScoreContribution[] }) {
  const max = Math.max(0.01, ...rows.map((r) => r.contribution));
  return (
    <ul className="space-y-1.5">
      {rows.map((r) => (
        <li key={r.component} className="text-xs">
          <div className="flex items-center justify-between text-ink-muted">
            <span>
              {r.label}
              <span className="ml-1 text-[10px] text-ink-dim">
                ({Math.round(r.weight * 100)}% · {r.score == null ? "n/a" : r.score})
              </span>
            </span>
            <span className="font-mono text-ink">+{r.contribution.toFixed(1)}</span>
          </div>
          <div className="mt-0.5 h-1 rounded bg-bg-subtle">
            <div
              className="h-1 rounded bg-accent"
              style={{ width: `${Math.max(2, (r.contribution / max) * 100)}%` }}
            />
          </div>
        </li>
      ))}
    </ul>
  );
}

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
  const { explanation } = useRecommendationExplanation(
    rec?.symbol ?? null,
    rec?.profile ?? "short_aggressive",
    rec?.horizon ?? "SHORT_2W",
  );

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
      {rec.is_held ? (
        <div
          className={`rounded border px-3 py-2 text-xs ${
            rec.warnings.includes("portfolio_concentration")
              ? "border-amber-500/40 bg-amber-500/10 text-amber-300"
              : "border-border bg-bg-subtle/40 text-ink-muted"
          }`}
        >
          <span className="font-medium">Portfolio:</span>{" "}
          {rec.portfolio_note ?? "Currently held."}
          {rec.held_quantity != null ? (
            <span className="ml-1 text-ink-dim">
              ({rec.held_quantity.toLocaleString()} sh
              {rec.held_avg_cost != null ? ` @ ${rec.held_avg_cost.toLocaleString()}` : ""})
            </span>
          ) : null}
        </div>
      ) : null}
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
      {explanation ? (
        <section>
          <h4 className="mb-2 text-xs uppercase tracking-wide text-ink-dim">
            Why this score
          </h4>
          <p className="mb-2 text-xs text-ink-muted">{explanation.summary}</p>
          <ContributionBreakdown rows={explanation.contributions} />
          <p className="mt-2 text-[10px] text-ink-dim">
            Final {explanation.final_score}/100 · action threshold{" "}
            {explanation.action_threshold_used} · weighted by{" "}
            {explanation.profile === "short_aggressive" ? "short-term" : "long-term"} profile
          </p>
        </section>
      ) : null}
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
