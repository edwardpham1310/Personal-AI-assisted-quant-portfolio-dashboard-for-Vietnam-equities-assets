"use client";

import type { RecommendationResult } from "@/hooks/useRecommendations";
import { ActionBadge } from "./ActionBadge";

export function RejectedRecsSection({
  results,
  onSelect,
}: {
  results: RecommendationResult[];
  onSelect?: (rec: RecommendationResult) => void;
}) {
  const rejected = results.filter((r) => r.status === "REJECTED");
  if (rejected.length === 0) return null;

  return (
    <section className="rounded border border-border bg-bg-panel p-4 opacity-90">
      <header className="mb-2">
        <h3 className="text-sm font-medium text-ink">Rejected recommendations</h3>
        <p className="text-[10px] text-ink-dim">
          A guardrail rejected these. Listed for audit only — not actionable.
        </p>
      </header>
      <ul className="space-y-2 text-xs">
        {rejected.map((r) => (
          <li
            key={`${r.symbol}-${r.horizon}`}
            className="flex items-center justify-between gap-2 border-t border-border pt-2 first:border-t-0"
          >
            <button
              type="button"
              onClick={() => onSelect?.(r)}
              className="flex items-center gap-3 text-left hover:text-ink"
            >
              <span className="font-mono">{r.symbol}</span>
              <ActionBadge action={r.action} />
              <span className="text-ink-dim">
                {r.warnings.slice(0, 2).join(", ") || "guardrail"}
              </span>
            </button>
            <span className="font-mono text-ink-dim">score {r.final_score}</span>
          </li>
        ))}
      </ul>
    </section>
  );
}
