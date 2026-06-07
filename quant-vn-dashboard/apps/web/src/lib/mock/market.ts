/** Deterministic mock data for the Market Overview page. */

export type IndexSnapshot = {
  code: string;
  name: string;
  close: number;
  change: number;
  change_pct: number;
  volume: number;
};

export const MOCK_INDICES: IndexSnapshot[] = [
  {
    code: "VNINDEX",
    name: "VN Index",
    close: 1280.5,
    change: 6.2,
    change_pct: 0.0049,
    volume: 720_000_000,
  },
  {
    code: "VN30",
    name: "VN30 Index",
    close: 1322.1,
    change: 8.4,
    change_pct: 0.0064,
    volume: 410_000_000,
  },
  {
    code: "HNXINDEX",
    name: "HNX Index",
    close: 240.7,
    change: -0.5,
    change_pct: -0.0021,
    volume: 95_000_000,
  },
  {
    code: "UPCOMINDEX",
    name: "UPCoM Index",
    close: 92.4,
    change: 0.1,
    change_pct: 0.0011,
    volume: 38_000_000,
  },
];

/** Honest coverage of breadth/top-movers: the whole market vs only the polled
 *  core "tracked universe". Set by the backend route. */
export type Coverage = "full_market" | "tracked_universe";

export type MarketBreadth = {
  advancers: number;
  decliners: number;
  unchanged: number;
  ceiling: number;
  floor: number;
  coverage?: Coverage;
  universe_size?: number;
};

export const MOCK_BREADTH: MarketBreadth = {
  advancers: 215,
  decliners: 168,
  unchanged: 44,
  ceiling: 8,
  floor: 3,
};

export type Mover = {
  symbol: string;
  price: number;
  change_pct: number;
  volume: number;
  value?: number;
};

export type TopMovers = {
  gainers: Mover[];
  losers: Mover[];
  by_value: Mover[];
  // Ranked by raw session volume (ordinal). Replaces the former, never-real
  // ``by_volume_spike`` (which needed an ADV-20d baseline the live feed lacks).
  by_volume: Mover[];
  coverage?: Coverage;
  universe_size?: number;
};

export const MOCK_TOP_MOVERS: TopMovers = {
  gainers: [
    { symbol: "FPT", price: 87_200, change_pct: 0.0234, volume: 4_200_000 },
    { symbol: "MWG", price: 42_850, change_pct: 0.0202, volume: 3_900_000 },
    { symbol: "VRE", price: 28_150, change_pct: 0.0175, volume: 2_800_000 },
  ],
  losers: [
    { symbol: "HPG", price: 24_850, change_pct: -0.022, volume: 5_400_000 },
    { symbol: "STB", price: 28_900, change_pct: -0.018, volume: 4_100_000 },
    { symbol: "VRE", price: 28_150, change_pct: -0.016, volume: 2_800_000 },
  ],
  by_value: [
    { symbol: "VCB", price: 89_000, change_pct: 0.008, volume: 1_700_000, value: 151_300_000_000 },
    { symbol: "FPT", price: 87_200, change_pct: 0.0234, volume: 4_200_000, value: 366_240_000_000 },
    { symbol: "MWG", price: 42_850, change_pct: 0.0202, volume: 3_900_000, value: 167_115_000_000 },
  ],
  by_volume: [
    { symbol: "HPG", price: 24_850, change_pct: -0.022, volume: 5_400_000 },
    { symbol: "FPT", price: 87_200, change_pct: 0.0234, volume: 4_200_000 },
    { symbol: "STB", price: 28_900, change_pct: -0.018, volume: 4_100_000 },
  ],
};

export type OHLCV = {
  ts: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
};

function pseudoHash(s: string): number {
  let h = 2_166_136_261;
  for (let i = 0; i < s.length; i++) {
    h ^= s.charCodeAt(i);
    h = (h * 16_777_619) >>> 0;
  }
  return (h % 10_000) / 10_000;
}

const REFERENCE_PRICE: Record<string, number> = {
  FPT: 86_000,
  MWG: 42_000,
  HPG: 25_000,
  VNM: 70_000,
  VCB: 88_000,
  VRE: 28_000,
  VNINDEX: 1_280,
  VN30: 1_320,
  HNXINDEX: 240,
  UPCOMINDEX: 92,
};

/**
 * Deterministic OHLCV walk. The same (symbol, day index) always returns the
 * same bar, so chart snapshots stay stable.
 */
export function makeMockOhlcv(symbol: string, days = 180): OHLCV[] {
  let price = REFERENCE_PRICE[symbol.toUpperCase()] ?? 50_000;
  const out: OHLCV[] = [];
  for (let i = 0; i < days; i++) {
    const drift = pseudoHash(`${symbol}-${i}`);
    const spreadSeed = pseudoHash(`${symbol}-spread-${i}`);
    const volumeSeed = pseudoHash(`${symbol}-vol-${i}`);
    const close = price * (1 + (drift - 0.5) * 0.04);
    const spread = 0.001 + spreadSeed * 0.004;
    const high = close * (1 + spread);
    const low = close * (1 - spread);
    const open = price * (1 + (drift - 0.5) * 0.02);
    const volume = 100_000 + Math.floor(volumeSeed * 500_000);
    const ts = new Date(Date.now() - (days - 1 - i) * 86_400_000);
    out.push({
      ts: ts.toISOString().slice(0, 10),
      open,
      high,
      low,
      close,
      volume,
    });
    price = close;
  }
  return out;
}

/** Equal-length comparison series of VNINDEX vs. VN30 (rebased to 100). */
export function makeMockIndexComparison(
  days = 90,
): { ts: string; vnindex: number; vn30: number }[] {
  const vni = makeMockOhlcv("VNINDEX", days);
  const vn30 = makeMockOhlcv("VN30", days);
  const v0 = vni[0]?.close ?? 1;
  const v30_0 = vn30[0]?.close ?? 1;
  return vni.map((b, i) => ({
    ts: b.ts,
    vnindex: (b.close / v0) * 100,
    vn30: ((vn30[i]?.close ?? v30_0) / v30_0) * 100,
  }));
}
