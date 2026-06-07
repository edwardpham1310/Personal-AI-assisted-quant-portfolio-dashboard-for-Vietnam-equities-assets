import { describe, expect, it, vi, beforeEach } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";

const apiMock = vi.fn();
vi.mock("@/lib/api", () => ({ useApi: () => apiMock }));

import { usePortfolioVsIndex } from "./usePortfolioVsIndex";

function route(equity: unknown, vnindex: unknown) {
  apiMock.mockImplementation((path?: string) => {
    if (typeof path !== "string") return Promise.resolve(undefined);
    if (path.startsWith("/portfolio/snapshots/run")) return Promise.resolve(undefined);
    if (path.startsWith("/portfolio/equity-curve")) return Promise.resolve(equity);
    if (path.startsWith("/market/ohlcv/daily/VNINDEX")) return Promise.resolve(vnindex);
    return Promise.resolve(undefined);
  });
}

beforeEach(() => apiMock.mockReset());

describe("usePortfolioVsIndex", () => {
  it("aligns on common dates and rebases both series to 100 (ascending)", async () => {
    route(
      [
        { ts: "2026-01-02", equity: 110 },
        { ts: "2026-01-01", equity: 100 }, // out of order on purpose
      ],
      [
        { ts: "2026-01-01", close: 1000 },
        { ts: "2026-01-02", close: 1050 },
      ],
    );
    const { result } = renderHook(() => usePortfolioVsIndex("1M"));
    await waitFor(() => expect(result.current.data.length).toBe(2));

    const d = result.current.data;
    expect(d.map((p) => p.ts)).toEqual(["2026-01-01", "2026-01-02"]); // ascending
    expect(d[0].portfolio).toBeCloseTo(100);
    expect(d[0].vnindex).toBeCloseTo(100);
    expect(d[1].portfolio).toBeCloseTo(110); // 110/100*100
    expect(d[1].vnindex).toBeCloseTo(105); // 1050/1000*100
  });

  it("returns honest-empty when there is no overlapping date", async () => {
    route(
      [{ ts: "2026-01-01", equity: 100 }],
      [{ ts: "2026-02-01", close: 1000 }],
    );
    const { result } = renderHook(() => usePortfolioVsIndex("1M"));
    // first paint is [], and it must stay [] after the fetch resolves
    await waitFor(() => expect(apiMock).toHaveBeenCalled());
    await new Promise((r) => setTimeout(r, 0));
    expect(result.current.data).toEqual([]);
  });

  it("returns empty when the equity curve has no snapshots yet", async () => {
    route([], [{ ts: "2026-01-01", close: 1000 }]);
    const { result } = renderHook(() => usePortfolioVsIndex("1M"));
    await waitFor(() => expect(apiMock).toHaveBeenCalled());
    await new Promise((r) => setTimeout(r, 0));
    expect(result.current.data).toEqual([]);
  });
});
