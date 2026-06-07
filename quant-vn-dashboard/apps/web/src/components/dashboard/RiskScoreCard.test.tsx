import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import type { RiskScore } from "@/hooks/usePortfolioRiskScore";

const hookMock = vi.fn();
vi.mock("@/hooks/usePortfolioRiskScore", () => ({
  usePortfolioRiskScore: () => hookMock(),
}));

import { RiskScoreCard } from "./RiskScoreCard";

function setHook(data: RiskScore | null, loading = false, error: string | null = null) {
  hookMock.mockReturnValue({ data, loading, error, refresh: vi.fn() });
}

beforeEach(() => hookMock.mockReset());

describe("RiskScoreCard", () => {
  it("shows an honest empty state when the score is null (no data)", () => {
    setHook({
      score: null,
      band: "unavailable",
      components: [
        { key: "concentration", label: "Concentration", available: false, weight: 0.3, reason: "no_priced_positions" },
        { key: "liquidity", label: "Liquidity", available: false, weight: 0, reason: "no_adv_baseline" },
      ],
      available_count: 0,
      total_count: 6,
    });
    render(<RiskScoreCard />);
    expect(screen.getByText(/Not enough data yet/i)).toBeDefined();
    // Unavailable components are listed with their reason (no fabricated number).
    expect(screen.getByText(/no adv baseline/i)).toBeDefined();
  });

  it("renders the score, band, and available component breakdown (partial)", () => {
    setHook({
      score: 62.5,
      band: "elevated",
      components: [
        { key: "concentration", label: "Concentration", available: true, score: 100, weight: 0.3, detail: "HHI 1.00 across 1 priced position(s)" },
        { key: "cash_buffer", label: "Cash buffer", available: true, score: 40, weight: 0.15, detail: "6% cash vs 10% target" },
        { key: "drawdown", label: "Drawdown", available: false, weight: 0.2, reason: "insufficient_history" },
        { key: "liquidity", label: "Liquidity", available: false, weight: 0, reason: "no_adv_baseline" },
      ],
      available_count: 2,
      total_count: 6,
    });
    render(<RiskScoreCard />);
    expect(screen.getByText("63")).toBeDefined(); // rounded score
    expect(screen.getByText("elevated")).toBeDefined();
    expect(screen.getByText("2/6 components")).toBeDefined();
    expect(screen.getByText(/HHI 1.00/)).toBeDefined(); // explainable detail
    expect(screen.getByText(/insufficient history/i)).toBeDefined(); // partial reason
  });

  it("shows an unavailable message on error", () => {
    setHook(null, false, "boom");
    render(<RiskScoreCard />);
    expect(screen.getByText(/unavailable right now/i)).toBeDefined();
  });
});
