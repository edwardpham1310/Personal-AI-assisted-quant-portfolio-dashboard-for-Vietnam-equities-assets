"use client";

import type { SignalCode } from "@/hooks/useScanner";

type Tone = "trend" | "momentum-up" | "momentum-down" | "volume" | "breakout" | "risk";

type SignalMeta = {
  label: string;
  tone: Tone;
  description: string;
};

/**
 * Display metadata for each scanner signal. Descriptions describe what the
 * indicator measured — never an action ("buy", "sell", "enter") — to keep the
 * UI in research-signal territory.
 */
export const SIGNAL_META: Record<SignalCode, SignalMeta> = {
  MA20_ABOVE_MA50: {
    label: "MA20>MA50",
    tone: "trend",
    description: "20-day moving average is above the 50-day moving average.",
  },
  PRICE_ABOVE_MA20: {
    label: "Px>MA20",
    tone: "trend",
    description: "Last price is above the 20-day moving average.",
  },
  RSI_OVERBOUGHT: {
    label: "RSI hi",
    tone: "momentum-up",
    description: "14-period RSI is above the overbought threshold.",
  },
  RSI_OVERSOLD: {
    label: "RSI lo",
    tone: "momentum-down",
    description: "14-period RSI is below the oversold threshold.",
  },
  VOLUME_SPIKE: {
    label: "Vol spike",
    tone: "volume",
    description: "Today's volume is meaningfully above the 20-day average.",
  },
  BREAKOUT_20D: {
    label: "BO 20D",
    tone: "breakout",
    description: "Price printed above the prior 20-day high.",
  },
  BREAKOUT_55D: {
    label: "BO 55D",
    tone: "breakout",
    description: "Price printed above the prior 55-day high.",
  },
  LOW_LIQUIDITY: {
    label: "Low liq",
    tone: "risk",
    description: "20-day average traded value is below the liquidity floor.",
  },
};

const TONE_CLASSES: Record<Tone, string> = {
  trend: "bg-accent-up/15 text-accent-up border-accent-up/30",
  "momentum-up": "bg-amber-500/15 text-amber-300 border-amber-500/30",
  "momentum-down": "bg-accent/15 text-accent border-accent/30",
  volume: "bg-purple-500/15 text-purple-300 border-purple-500/30",
  breakout: "bg-emerald-500/15 text-emerald-300 border-emerald-500/30",
  risk: "bg-accent-down/15 text-accent-down border-accent-down/30",
};

export function SignalBadge({ code }: { code: SignalCode }) {
  const meta = SIGNAL_META[code];
  return (
    <span
      data-signal={code}
      title={meta.description}
      aria-label={`${meta.label} signal: ${meta.description}`}
      className={`inline-flex items-center rounded border px-1.5 py-0.5 text-[10px] font-medium ${TONE_CLASSES[meta.tone]}`}
    >
      {meta.label}
    </span>
  );
}

export function SignalBadgeList({ codes }: { codes: SignalCode[] }) {
  if (codes.length === 0) {
    return <span className="text-[10px] text-ink-dim">—</span>;
  }
  return (
    <span className="inline-flex flex-wrap gap-1">
      {codes.map((c) => (
        <SignalBadge key={c} code={c} />
      ))}
    </span>
  );
}
