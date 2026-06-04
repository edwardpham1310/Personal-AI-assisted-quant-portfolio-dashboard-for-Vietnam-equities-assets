"use client";

import type { RangeKey, RangeOption } from "@/lib/dateRange";

/**
 * Compact date-range dropdown — a styled native `<select>` so it stays small,
 * accessible, and keyboard-friendly without pulling in a popover component.
 * Used by every time-series chart in place of wide segmented button groups.
 */
export function RangeSelect({
  value,
  options,
  onChange,
  label = "Range",
}: {
  value: RangeKey;
  options: RangeOption[];
  onChange: (key: RangeKey) => void;
  label?: string;
}) {
  return (
    <label className="inline-flex items-center gap-1 text-xs text-ink-dim">
      <span className="sr-only">{label}</span>
      <select
        aria-label={label}
        value={value}
        onChange={(e) => onChange(e.target.value as RangeKey)}
        className="rounded border border-border bg-bg-panel px-2 py-0.5 text-xs text-ink-muted hover:border-ink-dim focus:border-accent focus:outline-none"
      >
        {options.map((o) => (
          <option key={o.key} value={o.key}>
            {o.label}
          </option>
        ))}
      </select>
    </label>
  );
}
