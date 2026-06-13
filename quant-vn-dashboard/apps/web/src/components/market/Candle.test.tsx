import { describe, expect, it } from "vitest";
import { isValidElement } from "react";

import { Candle } from "./CandlestickChart";

type Bar = { open: number; high: number; low: number; close: number };

function el(bar: Bar) {
  return Candle({
    x: 0,
    y: 10,
    width: 8,
    height: 40,
    payload: { ts: "2026-01-01", volume: 0, range: [bar.low, bar.high], ma20: null, ma50: null, ma200: null, ...bar },
  });
}

describe("Candle", () => {
  it("renders a doji <line> on a flat / limit-locked day (high === low)", () => {
    const node = el({ open: 50, high: 50, low: 50, close: 50 });
    expect(isValidElement(node)).toBe(true);
    // The flat-day branch returns a single <line>, never null (the old bug).
    expect((node as React.ReactElement).type).toBe("line");
  });

  it("renders a full candle <g> on a normal day", () => {
    const node = el({ open: 50, high: 55, low: 48, close: 53 });
    expect(isValidElement(node)).toBe(true);
    expect((node as React.ReactElement).type).toBe("g");
  });

  it("renders nothing without a payload", () => {
    expect(Candle({ x: 0, y: 0, width: 8, height: 40 })).toBeNull();
  });
});
