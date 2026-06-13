"use client";

/**
 * Small freshness footnote for charts/cards. Honest about data age:
 *  - fresh:  "As of <when>"
 *  - stale:  "Latest synced · <when>" in amber (shown when we're displaying the
 *            last good dataset after a failed refresh, or a cold/cached source)
 *
 * Renders nothing when there's no timestamp and nothing is stale.
 */
function formatWhen(iso: string | null | undefined): string | null {
  if (!iso) return null;
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return String(iso);
  // Date-only for daily series; include time when the ISO carries one.
  const hasTime = /\d{2}:\d{2}/.test(iso);
  return hasTime ? d.toLocaleString() : d.toISOString().slice(0, 10);
}

export function StaleNote({
  asOf,
  stale = false,
  label,
}: {
  asOf?: string | null;
  stale?: boolean;
  /** Override the prefix (default "As of" / "Latest synced"). */
  label?: string;
}) {
  const when = formatWhen(asOf);
  if (!when && !stale) return null;
  const prefix = label ?? (stale ? "Latest synced" : "As of");
  return (
    <p
      className={`mt-2 text-[10px] ${stale ? "text-amber-400" : "text-ink-dim"}`}
      role="note"
    >
      {stale ? "⚠ " : ""}
      {prefix}
      {when ? ` · ${when}` : ""}
      {stale ? " (showing last synced data)" : ""}
    </p>
  );
}
