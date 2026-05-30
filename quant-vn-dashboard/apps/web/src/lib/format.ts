const VND_FMT = new Intl.NumberFormat("en-US");

export function formatVnd(value: number, opts: { compact?: boolean } = {}): string {
  if (opts.compact) {
    if (Math.abs(value) >= 1_000_000_000) return `${(value / 1_000_000_000).toFixed(2)}B VND`;
    if (Math.abs(value) >= 1_000_000) return `${(value / 1_000_000).toFixed(1)}M VND`;
    if (Math.abs(value) >= 1_000) return `${(value / 1_000).toFixed(1)}K VND`;
    return `${value.toFixed(0)} VND`;
  }
  return `${VND_FMT.format(Math.round(value))} VND`;
}

export function formatPct(value: number, fractionDigits = 2): string {
  return `${(value * 100).toFixed(fractionDigits)}%`;
}

export function formatNumber(value: number): string {
  return VND_FMT.format(Math.round(value));
}

export function signedColor(value: number): "up" | "down" | "neutral" {
  if (value > 0) return "up";
  if (value < 0) return "down";
  return "neutral";
}
