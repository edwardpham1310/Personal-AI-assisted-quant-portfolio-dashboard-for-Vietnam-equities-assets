import { describe, expect, it } from "vitest";

import { latestTimestamp, normalizeSeries } from "./chart";

type Row = { ts: string | null; v: number | null };

describe("normalizeSeries", () => {
  it("sorts ascending (oldest → newest)", () => {
    const rows: Row[] = [
      { ts: "2026-01-03", v: 3 },
      { ts: "2026-01-01", v: 1 },
      { ts: "2026-01-02", v: 2 },
    ];
    expect(normalizeSeries(rows, (r) => r.ts).map((r) => r.ts)).toEqual([
      "2026-01-01",
      "2026-01-02",
      "2026-01-03",
    ]);
  });

  it("drops rows with a missing/unparseable timestamp but keeps null metrics", () => {
    const rows: Row[] = [
      { ts: "2026-01-01", v: null }, // null metric kept (partial line)
      { ts: null, v: 9 }, // missing ts dropped
      { ts: "nonsense", v: 9 }, // unparseable dropped
    ];
    const out = normalizeSeries(rows, (r) => r.ts);
    expect(out).toEqual([{ ts: "2026-01-01", v: null }]);
  });

  it("de-duplicates by timestamp, last value wins, order preserved", () => {
    const rows: Row[] = [
      { ts: "2026-01-01", v: 1 },
      { ts: "2026-01-02", v: 2 },
      { ts: "2026-01-01", v: 10 }, // duplicate date → last wins
    ];
    expect(normalizeSeries(rows, (r) => r.ts)).toEqual([
      { ts: "2026-01-01", v: 10 },
      { ts: "2026-01-02", v: 2 },
    ]);
  });

  it("does not mutate the input", () => {
    const rows: Row[] = [
      { ts: "2026-01-02", v: 2 },
      { ts: "2026-01-01", v: 1 },
    ];
    const snapshot = JSON.stringify(rows);
    normalizeSeries(rows, (r) => r.ts);
    expect(JSON.stringify(rows)).toBe(snapshot);
  });
});

describe("latestTimestamp", () => {
  it("returns the newest timestamp", () => {
    const rows: Row[] = [
      { ts: "2026-01-01", v: 1 },
      { ts: "2026-01-05", v: 5 },
      { ts: "2026-01-03", v: 3 },
    ];
    expect(latestTimestamp(rows, (r) => r.ts)).toBe("2026-01-05");
  });

  it("returns null for an empty series", () => {
    expect(latestTimestamp([] as Row[], (r) => r.ts)).toBeNull();
  });
});
