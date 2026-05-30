"use client";

import type { ScannerStatus } from "@/hooks/useScanner";

type StatusMeta = {
  label: string;
  className: string;
  description: string;
};

const STATUS_META: Record<ScannerStatus, StatusMeta> = {
  BUY_CANDIDATE: {
    label: "Buy candidate",
    className: "bg-accent-up/15 text-accent-up border-accent-up/40",
    description:
      "Composite score is in the buy-candidate band based on trend, momentum, and volume.",
  },
  WATCH: {
    label: "Watch",
    className: "bg-accent/15 text-accent border-accent/40",
    description: "Setup is forming but not yet confirmed.",
  },
  HOLD: {
    label: "Hold",
    className: "bg-bg-subtle text-ink-muted border-border",
    description: "No actionable edge from the current scan.",
  },
  AVOID: {
    label: "Avoid",
    className: "bg-accent-down/15 text-accent-down border-accent-down/40",
    description: "Risk filters tripped — flagged for avoidance.",
  },
};

export function StatusBadge({ status }: { status: ScannerStatus }) {
  const meta = STATUS_META[status];
  return (
    <span className="inline-flex flex-col">
      <span
        data-status={status}
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
