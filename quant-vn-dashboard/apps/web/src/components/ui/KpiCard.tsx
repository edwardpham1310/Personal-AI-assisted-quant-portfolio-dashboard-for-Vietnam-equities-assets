import type { ReactNode } from "react";
import { Skeleton } from "./Skeleton";

type Tone = "neutral" | "up" | "down";

const TONE_CLASS: Record<Tone, string> = {
  neutral: "text-ink",
  up: "text-accent-up",
  down: "text-accent-down",
};

export type KpiCardProps = {
  label: string;
  value: ReactNode;
  hint?: ReactNode;
  tone?: Tone;
  loading?: boolean;
};

export function KpiCard({ label, value, hint, tone = "neutral", loading }: KpiCardProps) {
  return (
    <div className="rounded-lg border border-border bg-bg-panel px-4 py-3">
      <p className="text-xs text-ink-dim uppercase tracking-wider">{label}</p>
      <p className={`mt-1 text-2xl font-semibold ${TONE_CLASS[tone]} font-mono`}>
        {loading ? <Skeleton height={20} width={120} /> : value}
      </p>
      {hint ? <p className="mt-1 text-xs text-ink-dim">{hint}</p> : null}
    </div>
  );
}
