import { describe, expect, it } from "vitest";
import {
  rangeStartDate,
  rangeToDays,
  sortByTimeAsc,
  isoDate,
  OHLCV_RANGE_OPTIONS,
  EQUITY_RANGE_OPTIONS,
} from "./dateRange";

describe("sortByTimeAsc", () => {
  it("turns descending date-only input into ascending output", () => {
    const input = [{ ts: "2026-03-01" }, { ts: "2026-01-01" }, { ts: "2026-02-01" }];
    const out = sortByTimeAsc(input, (r) => r.ts);
    expect(out.map((r) => r.ts)).toEqual(["2026-01-01", "2026-02-01", "2026-03-01"]);
  });

  it("does not mutate the input array", () => {
    const input = [{ ts: "2026-03-01" }, { ts: "2026-01-01" }];
    const snapshot = input.map((r) => r.ts);
    sortByTimeAsc(input, (r) => r.ts);
    expect(input.map((r) => r.ts)).toEqual(snapshot);
  });

  it("handles ISO datetime strings", () => {
    const input = [
      { ts: "2026-01-01T15:00:00Z" },
      { ts: "2026-01-01T09:00:00Z" },
    ];
    const out = sortByTimeAsc(input, (r) => r.ts);
    expect(out[0].ts).toBe("2026-01-01T09:00:00Z");
  });

  it("filters out missing/invalid timestamps", () => {
    const input = [
      { ts: "2026-02-01" },
      { ts: null },
      { ts: "not-a-date" },
      { ts: "2026-01-01" },
    ];
    const out = sortByTimeAsc(input, (r) => r.ts as string | null);
    expect(out.map((r) => r.ts)).toEqual(["2026-01-01", "2026-02-01"]);
  });

  it("supports epoch-number timestamps", () => {
    const input = [{ t: 3000 }, { t: 1000 }, { t: 2000 }];
    const out = sortByTimeAsc(input, (r) => r.t);
    expect(out.map((r) => r.t)).toEqual([1000, 2000, 3000]);
  });
});

describe("rangeStartDate", () => {
  it("returns null for ALL (no lower bound)", () => {
    expect(rangeStartDate("ALL")).toBeNull();
  });

  it("anchors YTD to Jan 1 of the current year", () => {
    const now = new Date("2026-06-15T00:00:00Z");
    expect(isoDate(rangeStartDate("YTD", now)!)).toBe("2026-01-01");
  });

  it("subtracts whole years for 1Y", () => {
    const now = new Date("2026-06-15T00:00:00Z");
    expect(isoDate(rangeStartDate("1Y", now)!)).toBe("2025-06-15");
  });

  it("subtracts one day for 1D", () => {
    const now = new Date("2026-06-15T00:00:00Z");
    expect(isoDate(rangeStartDate("1D", now)!)).toBe("2026-06-14");
  });
});

describe("standard range option sets", () => {
  const standard = ["1D", "1W", "1M", "3M", "6M", "YTD", "1Y"];

  it("OHLCV options are the standard set without All (365-day cap)", () => {
    expect(OHLCV_RANGE_OPTIONS.map((o) => o.key)).toEqual(standard);
    expect(OHLCV_RANGE_OPTIONS.some((o) => o.key === "ALL")).toBe(false);
  });

  it("equity options are the standard set plus All", () => {
    expect(EQUITY_RANGE_OPTIONS.map((o) => o.key)).toEqual([...standard, "ALL"]);
  });

  it("neither list offers the non-standard 5D/2W/2Y/5Y options", () => {
    const offered = [...OHLCV_RANGE_OPTIONS, ...EQUITY_RANGE_OPTIONS].map((o) => o.key);
    for (const k of ["5D", "2W", "2Y", "5Y"]) expect(offered).not.toContain(k);
  });
});

describe("rangeToDays", () => {
  it("clamps to the backend 365-day daily cap", () => {
    expect(rangeToDays("1Y")).toBeLessThanOrEqual(365);
    expect(rangeToDays("5Y")).toBe(365);
  });

  it("returns a small lookback for short ranges", () => {
    const now = new Date("2026-06-15T00:00:00Z");
    expect(rangeToDays("5D", now)).toBe(6); // 5 days back, inclusive
  });
});
