"use client";

/**
 * Compact 0–100 score with a mini horizontal bar. Bar color shifts from
 * red→amber→green as the score climbs so the table scans well at a glance.
 */
export function ScoreCell({
  value,
  label,
}: {
  value: number | null | undefined;
  /** Used in aria-label so screen readers know which score this is. */
  label?: string;
}) {
  if (value == null || Number.isNaN(value)) {
    return <span className="text-[11px] text-ink-dim">—</span>;
  }
  const clamped = Math.max(0, Math.min(100, value));
  const tone =
    clamped >= 70
      ? "bg-accent-up"
      : clamped >= 40
        ? "bg-amber-400"
        : "bg-accent-down";

  return (
    <span
      className="inline-flex flex-col items-end gap-0.5"
      aria-label={label ? `${label}: ${clamped.toFixed(0)} of 100` : undefined}
    >
      <span className="font-mono text-xs text-ink">{clamped.toFixed(0)}</span>
      <span className="block h-1 w-12 overflow-hidden rounded bg-bg-subtle">
        <span
          className={`block h-full ${tone}`}
          style={{ width: `${clamped}%` }}
        />
      </span>
    </span>
  );
}
