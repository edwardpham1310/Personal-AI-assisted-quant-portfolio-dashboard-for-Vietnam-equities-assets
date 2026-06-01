"use client";

import type { RecommendationAction, RecommendationStatus } from "@/hooks/useRecommendations";

type ActionMeta = {
  label: string;
  className: string;
  description: string;
};

export const ACTION_META: Record<RecommendationAction, ActionMeta> = {
  BUY_CANDIDATE: {
    label: "Buy candidate",
    className: "bg-accent-up/15 text-accent-up border-accent-up/40",
    description: "Composite score and trend are in the buy-candidate band.",
  },
  WATCH: {
    label: "Watch",
    className: "bg-accent/15 text-accent border-accent/40",
    description: "Setup is forming but not yet confirmed.",
  },
  HOLD: {
    label: "Hold",
    className: "bg-bg-subtle text-ink-muted border-border",
    description: "No edge surfaced from the current scan.",
  },
  REDUCE: {
    label: "Reduce",
    className: "bg-amber-500/15 text-amber-400 border-amber-500/40",
    description: "Score weakened while holding — research-only suggestion to lighten exposure.",
  },
  SELL_CANDIDATE: {
    label: "Sell candidate",
    className: "bg-accent-down/15 text-accent-down border-accent-down/40",
    description: "Downtrend confirmed while held — research-only suggestion to exit.",
  },
  AVOID: {
    label: "Avoid",
    className: "bg-accent-down/15 text-accent-down border-accent-down/40",
    description: "Risk filters tripped — flagged for avoidance.",
  },
  REJECTED: {
    label: "Rejected",
    className: "bg-accent-down/25 text-accent-down border-accent-down/60 line-through",
    description: "A guardrail rejected this candidate. Not actionable.",
  },
};

export function ActionBadge({ action }: { action: RecommendationAction }) {
  const meta = ACTION_META[action];
  return (
    <span className="inline-flex flex-col">
      <span
        data-action={action}
        title={meta.description}
        aria-label={`${meta.label} — research signal, not financial advice.`}
        className={`inline-flex items-center rounded-full border px-2 py-0.5 text-[11px] font-medium ${meta.className}`}
      >
        {meta.label}
      </span>
      <span className="mt-0.5 text-[9px] leading-tight text-ink-dim">
        research signal · not advice
      </span>
    </span>
  );
}

const STATUS_META: Record<RecommendationStatus, { label: string; cls: string }> = {
  VALID: {
    label: "Valid",
    cls: "bg-accent-up/15 text-accent-up border-accent-up/40",
  },
  WARNING: {
    label: "Warning",
    cls: "bg-amber-500/15 text-amber-400 border-amber-500/40",
  },
  REJECTED: {
    label: "Rejected",
    cls: "bg-accent-down/25 text-accent-down border-accent-down/60",
  },
};

export function RecoStatusBadge({ status }: { status: RecommendationStatus }) {
  const meta = STATUS_META[status];
  return (
    <span
      data-reco-status={status}
      className={`inline-flex items-center rounded border px-2 py-0.5 text-[10px] font-medium ${meta.cls}`}
    >
      {meta.label}
    </span>
  );
}
