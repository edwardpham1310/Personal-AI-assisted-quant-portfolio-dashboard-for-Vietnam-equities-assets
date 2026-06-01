"use client";

import type { SignalCode } from "@/hooks/useScanner";
import { SIGNAL_META } from "./SignalBadge";

const ALL_SIGNALS: SignalCode[] = [
  "MA20_ABOVE_MA50",
  "PRICE_ABOVE_MA20",
  "BREAKOUT_20D",
  "BREAKOUT_55D",
  "VOLUME_SPIKE",
  "RSI_OVERBOUGHT",
  "RSI_OVERSOLD",
  "LOW_LIQUIDITY",
];

export function SignalFilterBar({
  selected,
  onChange,
}: {
  selected: SignalCode[];
  onChange: (next: SignalCode[]) => void;
}) {
  function toggle(code: SignalCode) {
    if (selected.includes(code)) {
      onChange(selected.filter((c) => c !== code));
    } else {
      onChange([...selected, code]);
    }
  }

  return (
    <div className="flex flex-wrap items-center gap-2" role="group" aria-label="Filter by signal">
      <span className="text-[11px] uppercase tracking-wide text-ink-dim">Filter</span>
      {ALL_SIGNALS.map((code) => {
        const active = selected.includes(code);
        return (
          <button
            key={code}
            type="button"
            onClick={() => toggle(code)}
            aria-pressed={active}
            title={SIGNAL_META[code].description}
            className={`rounded border px-2 py-0.5 text-[11px] transition-colors ${
              active
                ? "border-accent bg-accent/15 text-accent"
                : "border-border bg-bg-panel text-ink-muted hover:border-ink-dim"
            }`}
          >
            {SIGNAL_META[code].label}
          </button>
        );
      })}
      {selected.length > 0 ? (
        <button
          type="button"
          onClick={() => onChange([])}
          className="text-[11px] text-ink-dim underline hover:text-ink"
        >
          Clear
        </button>
      ) : null}
    </div>
  );
}
