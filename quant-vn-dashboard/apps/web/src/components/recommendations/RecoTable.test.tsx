import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { RecoTable } from "./RecoTable";
import type { RecommendationResult } from "@/hooks/useRecommendations";

function makeRec(overrides: Partial<RecommendationResult> = {}): RecommendationResult {
  return {
    symbol: "FPT",
    profile: "short_aggressive",
    horizon: "SHORT_2W",
    action: "WATCH",
    status: "VALID",
    confidence: 0.6,
    final_score: 60,
    scores: {
      trend: 60,
      momentum: 60,
      volume: 60,
      liquidity: 60,
      risk: 40,
      risk_inverse: 60,
      market_regime: 60,
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
    data_status: "FRESH",
    latest_quote: null,
    chart_context: null,
    chart_url: "/market/FPT",
    disclaimer: "research signal · not financial advice · no orders placed",
    is_held: false,
    held_weight_pct: null,
    held_quantity: null,
    held_avg_cost: null,
    held_unrealized_pct: null,
    portfolio_note: null,
    ...overrides,
  };
}

describe("RecoTable", () => {
  it("renders the empty state when no results", () => {
    render(<RecoTable results={[]} />);
    expect(screen.getByText(/No recommendations yet/i)).toBeDefined();
    expect(screen.queryByRole("table")).toBeNull();
  });

  it("renders one row per recommendation", () => {
    const rows = [
      makeRec({ symbol: "FPT" }),
      makeRec({ symbol: "MWG", action: "BUY_CANDIDATE", confidence: 0.8 }),
    ];
    render(<RecoTable results={rows} />);
    const tbody = screen.getByRole("table").querySelector("tbody")!;
    expect(within(tbody).getAllByRole("row").length).toBe(2);
    expect(screen.getByTestId("reco-row-FPT")).toBeDefined();
    expect(screen.getByTestId("reco-row-MWG")).toBeDefined();
  });

  it("sorts by confidence desc by default", () => {
    const rows = [
      makeRec({ symbol: "LOW", confidence: 0.2 }),
      makeRec({ symbol: "HIGH", confidence: 0.9 }),
    ];
    render(<RecoTable results={rows} />);
    const tbody = screen.getByRole("table").querySelector("tbody")!;
    const orderedRows = within(tbody).getAllByRole("row");
    expect(orderedRows[0].getAttribute("data-testid")).toBe("reco-row-HIGH");
    expect(orderedRows[1].getAttribute("data-testid")).toBe("reco-row-LOW");
  });

  it("filters to a single action when its chip is selected", () => {
    const rows = [
      makeRec({ symbol: "FPT", action: "WATCH" }),
      makeRec({ symbol: "MWG", action: "BUY_CANDIDATE" }),
    ];
    render(<RecoTable results={rows} />);
    fireEvent.click(screen.getByRole("button", { name: "BUY_CANDIDATE" }));
    const tbody = screen.getByRole("table").querySelector("tbody")!;
    const orderedRows = within(tbody).getAllByRole("row");
    expect(orderedRows.length).toBe(1);
    expect(orderedRows[0].getAttribute("data-testid")).toBe("reco-row-MWG");
  });

  it("invokes onSelect with the row when clicked", () => {
    const onSelect = vi.fn();
    const rec = makeRec({ symbol: "FPT" });
    render(<RecoTable results={[rec]} onSelect={onSelect} />);
    fireEvent.click(screen.getByTestId("reco-row-FPT"));
    expect(onSelect).toHaveBeenCalledTimes(1);
    expect(onSelect.mock.calls[0][0].symbol).toBe("FPT");
  });
});
