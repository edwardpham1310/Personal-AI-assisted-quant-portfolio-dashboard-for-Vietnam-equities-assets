const VND_FMT = new Intl.NumberFormat("en-US");
const PLACEHOLDER = "—";

function isFiniteNumber(value: number | null | undefined): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

export function formatVnd(value: number | null | undefined, opts: { compact?: boolean } = {}): string {
  if (!isFiniteNumber(value)) return PLACEHOLDER;
  if (opts.compact) {
    if (Math.abs(value) >= 1_000_000_000) return `${(value / 1_000_000_000).toFixed(2)}B VND`;
    if (Math.abs(value) >= 1_000_000) return `${(value / 1_000_000).toFixed(1)}M VND`;
    if (Math.abs(value) >= 1_000) return `${(value / 1_000).toFixed(1)}K VND`;
    return `${value.toFixed(0)} VND`;
  }
  return `${VND_FMT.format(Math.round(value))} VND`;
}

export function formatPct(value: number | null | undefined, fractionDigits = 2): string {
  if (!isFiniteNumber(value)) return PLACEHOLDER;
  return `${(value * 100).toFixed(fractionDigits)}%`;
}

export function formatNumber(value: number | null | undefined): string {
  if (!isFiniteNumber(value)) return PLACEHOLDER;
  return VND_FMT.format(Math.round(value));
}

export function signedColor(value: number | null | undefined): "up" | "down" | "neutral" {
  if (!isFiniteNumber(value)) return "neutral";
  if (value > 0) return "up";
  if (value < 0) return "down";
  return "neutral";
}
