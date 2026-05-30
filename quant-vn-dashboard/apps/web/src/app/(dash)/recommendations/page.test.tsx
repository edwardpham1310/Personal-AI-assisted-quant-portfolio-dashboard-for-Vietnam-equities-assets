import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import type {
  RecommendationResult,
} from "@/hooks/useRecommendations";

const apiMock = vi.fn();

vi.mock("@/lib/api", () => ({
  useApi: () => apiMock,
  ApiError: class ApiError extends Error {},
}));

const refreshMock = vi.fn();
let mockResults: RecommendationResult[] = [];
let mockLoading = false;
let mockError: string | null = null;

vi.mock("@/hooks/useRecommendations", async () => {
  const actual =
    await vi.importActual<typeof import("@/hooks/useRecommendations")>(
      "@/hooks/useRecommendations",
    );
  return {
    ...actual,
    useWatchlistRecommendations: () => ({
      results: mockResults,
      loading: mockLoading,
      error: mockError,
      refresh: refreshMock,
    }),
  };
});

import RecommendationsPage from "./page";

const FPT_REC: RecommendationResult = {
  symbol: "FPT",
  profile: "short_aggressive",
  horizon: "SHORT_2W",
  action: "BUY_CANDIDATE",
  status: "VALID",
  confidence: 0.8,
  final_score: 80,
  scores: {
    trend: 80,
    momentum: 70,
    volume: 60,
    liquidity: 80,
    risk: 30,
    risk_inverse: 70,
    market_regime: 70,
    portfolio_fit: 100,
    ml_probability: null,
  },
  last_price: 100000,
  entry_zone_low: 98000,
  entry_zone_high: 102000,
  stop_loss: 95000,
  take_profit_1: 110000,
  take_profit_2: 115000,
  position_size_vnd: 50_000_000,
  estimated_quantity: 500,
  estimated_total_cost: 50_300_000,
  trend: "UPTREND",
  signals: [],
  reasons: ["TREND_UPTREND_CONFIRMED"],
  warnings: [],
  as_of: new Date().toISOString(),
  avg_value_20d: null,
  disclaimer: "research signal · not financial advice · no orders placed",
};

beforeEach(() => {
  apiMock.mockReset();
  refreshMock.mockReset();
  mockResults = [];
  mockLoading = false;
  mockError = null;
});

describe("RecommendationsPage", () => {
  it("shows the research-only disclaimer in the header", async () => {
    apiMock.mockResolvedValue([]);
    render(<RecommendationsPage />);
    expect(
      screen.getByText(/Research signals · Rule-based · Not financial advice/i),
    ).toBeDefined();
  });

  it("prompts the user to pick a watchlist when none is selected", async () => {
    apiMock.mockResolvedValue([]);
    render(<RecommendationsPage />);
    await waitFor(() =>
      expect(screen.getByText(/Pick a watchlist/i)).toBeDefined(),
    );
  });

  it("renders the table when a watchlist is selected and results arrive", async () => {
    apiMock.mockResolvedValue([
      { id: "wl-1", name: "Main" },
    ]);
    mockResults = [FPT_REC];
    render(<RecommendationsPage />);
    await waitFor(() => {
      expect(screen.getByTestId("reco-row-FPT")).toBeDefined();
    });
  });

  it("renders the rejected section when a result has status REJECTED", async () => {
    apiMock.mockResolvedValue([{ id: "wl-1", name: "Main" }]);
    mockResults = [
      { ...FPT_REC, action: "REJECTED", status: "REJECTED", warnings: ["low_liquidity"] },
    ];
    render(<RecommendationsPage />);
    await waitFor(() => {
      expect(screen.getByText(/Rejected recommendations/i)).toBeDefined();
    });
  });
});
