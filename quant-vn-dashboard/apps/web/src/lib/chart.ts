/**
 * Shared chart styling + time-series normalization.
 *
 * Centralises the dark-theme axis/tooltip/grid styling so every chart renders
 * consistently, and provides `normalizeSeries` — the canonical transform for
 * time-series data: sort ascending (oldest→newest), drop rows with a missing /
 * unparseable timestamp, and de-duplicate by timestamp (last value wins). It
 * deliberately keeps rows whose *metric* fields are null so a partial line can
 * still render; only a missing timestamp removes a row.
 */

import { sortByTimeAsc } from "./dateRange";

export const GRID_STROKE = "#21262d";

export const AXIS_TICK = { fill: "#8b949e", fontSize: 10 } as const;

export const TOOLTIP_STYLE = {
  background: "#0b0d10",
  border: "1px solid #21262d",
  fontSize: 12,
} as const;

export const TOOLTIP_LABEL_STYLE = { color: "#e6edf3" } as const;

/** Up/down/neutral + a small categorical palette, used across bar/line charts. */
export const CHART_COLORS = {
  up: "#22c55e",
  down: "#ef4444",
  primary: "#4f8bf0",
  series: ["#4f8bf0", "#22c55e", "#a855f7", "#f59e0b", "#06b6d4", "#84cc16", "#ec4899", "#64748b"],
} as const;

/**
 * Normalize a time-series: ascending by timestamp, missing-timestamp rows
 * dropped, duplicate timestamps collapsed (last wins). Never mutates the input.
 */
export function normalizeSeries<T>(
  rows: readonly T[],
  getTime: (row: T) => string | number | null | undefined,
): T[] {
  const sorted = sortByTimeAsc(rows, getTime);
  const byKey = new Map<string, T>();
  for (const row of sorted) {
    const raw = getTime(row);
    const key = typeof raw === "number" ? String(raw) : String(raw);
    byKey.set(key, row); // last wins; iteration order stays ascending
  }
  return [...byKey.values()];
}

/** Latest timestamp in a series (already-normalized or not), or null. */
export function latestTimestamp<T>(
  rows: readonly T[],
  getTime: (row: T) => string | number | null | undefined,
): string | null {
  const sorted = sortByTimeAsc(rows, getTime);
  if (sorted.length === 0) return null;
  const raw = getTime(sorted[sorted.length - 1]);
  return raw == null ? null : String(raw);
}
