import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { ScoreBreakdown } from "./ScoreBreakdown";
import type { RecommendationScores } from "@/hooks/useRecommendations";

const FULL_SCORES: RecommendationScores = {
  trend: 70,
  momentum: 60,
  volume: 50,
  liquidity: 80,
  risk: 30,
  risk_inverse: 70,
  market_regime: 60,
  portfolio_fit: 100,
  ml_probability: null,
};

describe("ScoreBreakdown", () => {
  it("renders the chart container when scores are present", () => {
    render(<ScoreBreakdown scores={FULL_SCORES} />);
    expect(screen.getByTestId("score-breakdown-chart")).toBeDefined();
  });

  it("shows the 'Phase 2' note when ml_probability is null", () => {
    render(<ScoreBreakdown scores={FULL_SCORES} />);
    expect(screen.getByText(/Phase 2/)).toBeDefined();
  });

  it("renders the empty state when every score is zero and ml is null", () => {
    const zeros: RecommendationScores = {
      trend: 0,
      momentum: 0,
      volume: 0,
      liquidity: 0,
      risk: 0,
      risk_inverse: 0,
      market_regime: 0,
      portfolio_fit: 0,
      ml_probability: null,
    };
    render(<ScoreBreakdown scores={zeros} />);
    expect(screen.getByText(/No score data/i)).toBeDefined();
  });

  it("renders the chart (no Phase-2 note) when ml_probability is provided", () => {
    render(
      <ScoreBreakdown
        scores={{ ...FULL_SCORES, ml_probability: 0.7 }}
      />,
    );
    expect(screen.getByTestId("score-breakdown-chart")).toBeDefined();
    expect(screen.queryByText(/Phase 2/)).toBeNull();
  });
});
