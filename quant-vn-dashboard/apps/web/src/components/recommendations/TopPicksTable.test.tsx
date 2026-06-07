import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import type { TopPicks } from "@/hooks/useTopPicks";

const hookMock = vi.fn();
vi.mock("@/hooks/useTopPicks", () => ({ useTopPicks: () => hookMock() }));

import { TopPicksTable } from "./TopPicksTable";

function setHook(data: TopPicks | null, loading = false, error: string | null = null) {
  hookMock.mockReturnValue({ data, loading, error, refresh: vi.fn() });
}

beforeEach(() => hookMock.mockReset());

describe("TopPicksTable", () => {
  it("shows an honest empty state when there are no picks", () => {
    setHook({ picks: [], coverage: "tracked_universe", universe_size: 0 });
    render(<TopPicksTable />);
    expect(screen.getByText(/No picks available/i)).toBeDefined();
    expect(screen.getByText(/Tracked universe/i)).toBeDefined();
  });

  it("renders picks with safe strength/signal labels (no advice wording)", () => {
    setHook({
      coverage: "tracked_universe",
      universe_size: 6,
      picks: [
        {
          symbol: "FPT",
          quant_score: 82,
          strength: "Strong",
          signal: "Actionable",
          confidence: 0.7,
          reasons: ["Uptrend with volume confirmation"],
          risks: [],
          price: 86000,
          change_pct: 0.012,
          volume: 4_200_000,
          value: 360_000_000_000,
        },
      ],
    });
    const { container } = render(<TopPicksTable />);
    expect(screen.getByText("FPT")).toBeDefined();
    expect(screen.getByText("82")).toBeDefined();
    expect(screen.getByText("Strong")).toBeDefined();
    expect(screen.getByText("Actionable")).toBeDefined();
    // No financial-advice wording anywhere in the rendered table.
    const text = (container.textContent ?? "").toLowerCase();
    for (const w of ["guaranteed", "sure profit", "must buy"]) {
      expect(text).not.toContain(w);
    }
  });

  it("disables Add-to-Watchlist until a handler is provided", () => {
    setHook({
      coverage: "tracked_universe",
      universe_size: 6,
      picks: [
        { symbol: "FPT", quant_score: 70, strength: "Neutral", signal: "Watch", confidence: 0.5, reasons: [], risks: [] },
      ],
    });
    render(<TopPicksTable />);
    const btn = screen.getByRole("button", { name: "＋" });
    expect(btn.hasAttribute("disabled")).toBe(true);
  });
});
