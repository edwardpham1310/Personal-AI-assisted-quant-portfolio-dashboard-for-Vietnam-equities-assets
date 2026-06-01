import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { AllocationDonut } from "./AllocationDonut";
import type { EnrichedPosition } from "@/hooks/portfolio-types";

function makePosition(overrides: Partial<EnrichedPosition>): EnrichedPosition {
  const base: EnrichedPosition = {
    id: "pos-1",
    account_id: "acc-1",
    symbol: "FPT",
    exchange: "HOSE",
    quantity: 1_000,
    sellable_quantity: 1_000,
    pending_quantity: 0,
    avg_cost: 120_000,
    market_price: 130_000,
    market_value: 130_000_000,
    unrealized_pnl: 10_000_000,
    unrealized_pnl_pct: 8.33,
    weight: 50,
    strategy_tag: null,
    note: null,
    warnings: [],
    last_marked_at: null,
  };
  return { ...base, ...overrides };
}

describe("AllocationDonut", () => {
  it("renders an empty state when there are no positions (does not crash)", () => {
    render(<AllocationDonut positions={[]} />);
    expect(screen.getByText(/No allocation yet/i)).toBeDefined();
  });

  it("renders empty state when every position has zero market value", () => {
    const rows = [
      makePosition({ symbol: "FPT", market_value: null }),
      makePosition({ id: "p2", symbol: "HPG", market_value: 0 }),
    ];
    render(<AllocationDonut positions={rows} />);
    expect(screen.getByText(/No allocation yet/i)).toBeDefined();
  });

  it("mounts the recharts container when two positions have market value", () => {
    const rows = [
      makePosition({ symbol: "FPT", market_value: 130_000_000 }),
      makePosition({ id: "p2", symbol: "HPG", market_value: 70_000_000 }),
    ];
    const { container } = render(<AllocationDonut positions={rows} />);
    expect(screen.getByTestId("allocation-donut")).toBeDefined();
    // Recharts can't measure the container in jsdom and skips drawing the
    // SVG cells, but the ResponsiveContainer wrapper does mount. That's
    // enough to prove the data path didn't fall back to the empty state.
    expect(container.querySelector(".recharts-responsive-container")).not.toBeNull();
    expect(screen.queryByText(/No allocation yet/i)).toBeNull();
  });
});
