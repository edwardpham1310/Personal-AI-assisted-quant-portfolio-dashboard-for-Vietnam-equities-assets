/**
 * Shared date-range options + defensive chronological sorting for charts.
 *
 * Two concerns live here so every time-series chart behaves identically:
 *  1. A small set of named lookback ranges rendered in the compact RangeSelect.
 *  2. `sortByTimeAsc` — a non-mutating ascending sort used as a defensive guard
 *     before any time-series renders, so a chart never plots right-to-left even
 *     if a data source returns rows out of order.
 */

export type RangeKey =
  | "1D"
  | "5D"
  | "1W"
  | "2W"
  | "1M"
  | "3M"
  | "6M"
  | "YTD"
  | "1Y"
  | "2Y"
  | "5Y"
  | "ALL";

export type RangeOption = { key: RangeKey; label: string };

/**
 * The standard dashboard range set: 1D · 1W · 1M · 3M · 6M · YTD · 1Y · All.
 * Every time-series chart draws from one of the two lists below so the dropdown
 * is consistent across the app. (`5D`/`2W`/`2Y`/`5Y` remain valid keys for the
 * helpers but are not offered — the standard set keeps the UI compact.)
 */

/**
 * Ranges for daily OHLCV charts (candlestick, index comparison,
 * portfolio-vs-VNINDEX). The standard set MINUS `All`/multi-year, because the
 * backend daily-history endpoint hard-caps at 365 days. `1D` shows the latest
 * one or two daily bars.
 */
export const OHLCV_RANGE_OPTIONS: RangeOption[] = [
  { key: "1D", label: "1D" },
  { key: "1W", label: "1W" },
  { key: "1M", label: "1M" },
  { key: "3M", label: "3M" },
  { key: "6M", label: "6M" },
  { key: "YTD", label: "YTD" },
  { key: "1Y", label: "1Y" },
];

/**
 * Ranges for the DB-backed equity curve, which has no 365-day cap. The full
 * standard set including `All` (the entire forward-only NAV history).
 */
export const EQUITY_RANGE_OPTIONS: RangeOption[] = [
  { key: "1D", label: "1D" },
  { key: "1W", label: "1W" },
  { key: "1M", label: "1M" },
  { key: "3M", label: "3M" },
  { key: "6M", label: "6M" },
  { key: "YTD", label: "YTD" },
  { key: "1Y", label: "1Y" },
  { key: "ALL", label: "All" },
];

/** Format a Date as an inclusive ISO date (YYYY-MM-DD). */
export function isoDate(d: Date): string {
  return d.toISOString().slice(0, 10);
}

/**
 * Inclusive lookback start for a range key, relative to `now`. Returns `null`
 * for `ALL` (no lower bound). Uses real calendar arithmetic so `YTD` is Jan 1
 * and month/year ranges respect varying month lengths and leap years.
 */
export function rangeStartDate(key: RangeKey, now: Date = new Date()): Date | null {
  if (key === "ALL") return null;
  // Compute in UTC so the result stays consistent with `isoDate` (which emits
  // the UTC calendar date) regardless of the viewer's timezone.
  if (key === "YTD") return new Date(Date.UTC(now.getUTCFullYear(), 0, 1));
  const d = new Date(now);
  switch (key) {
    case "1D":
      d.setUTCDate(d.getUTCDate() - 1);
      break;
    case "5D":
      d.setUTCDate(d.getUTCDate() - 5);
      break;
    case "1W":
      d.setUTCDate(d.getUTCDate() - 7);
      break;
    case "2W":
      d.setUTCDate(d.getUTCDate() - 14);
      break;
    case "1M":
      d.setUTCMonth(d.getUTCMonth() - 1);
      break;
    case "3M":
      d.setUTCMonth(d.getUTCMonth() - 3);
      break;
    case "6M":
      d.setUTCMonth(d.getUTCMonth() - 6);
      break;
    case "1Y":
      d.setUTCFullYear(d.getUTCFullYear() - 1);
      break;
    case "2Y":
      d.setUTCFullYear(d.getUTCFullYear() - 2);
      break;
    case "5Y":
      d.setUTCFullYear(d.getUTCFullYear() - 5);
      break;
  }
  return d;
}

/**
 * Lookback in whole days for OHLCV hooks that take a day count. Clamped to
 * [1, 365] to respect the backend daily-history cap. `ALL` (no OHLCV option
 * uses it) falls back to the 365-day cap.
 */
export function rangeToDays(key: RangeKey, now: Date = new Date()): number {
  const start = rangeStartDate(key, now);
  if (start === null) return 365;
  const days = Math.round((now.getTime() - start.getTime()) / 86_400_000) + 1;
  return Math.min(365, Math.max(1, days));
}

/**
 * Return a NEW array sorted ascending (oldest→newest) by the supplied
 * timestamp accessor. Never mutates the input (safe for props/cache/hook data).
 * Accepts ISO datetime strings, date-only `YYYY-MM-DD`, or epoch numbers;
 * rows whose timestamp is missing/unparseable are filtered out.
 */
export function sortByTimeAsc<T>(
  rows: readonly T[],
  getTime: (row: T) => string | number | null | undefined,
): T[] {
  return rows
    .map((row) => {
      const raw = getTime(row);
      const t = raw == null ? NaN : typeof raw === "number" ? raw : Date.parse(raw);
      return { row, t };
    })
    .filter((p) => Number.isFinite(p.t))
    .sort((a, b) => a.t - b.t)
    .map((p) => p.row);
}
