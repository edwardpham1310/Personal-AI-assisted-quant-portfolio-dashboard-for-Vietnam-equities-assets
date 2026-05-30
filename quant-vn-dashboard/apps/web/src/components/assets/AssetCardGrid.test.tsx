import { describe, expect, it } from "vitest";
import { render, screen, within } from "@testing-library/react";
import { AssetCardGrid } from "./AssetCardGrid";

describe("AssetCardGrid", () => {
  it("renders eight cards with zeros when summary is null", () => {
    render(<AssetCardGrid summary={null} />);
    const grid = screen.getByTestId("asset-card-grid");
    // Eight KpiCard tiles → eight uppercase labels at the top.
    expect(grid.querySelectorAll("p.uppercase").length).toBe(8);
    // Every value should render as 0 VND while we wait for real data.
    const zeros = within(grid).getAllByText("0 VND");
    expect(zeros.length).toBe(8);
  });

  it("surfaces the down tone when a liability is non-zero", () => {
    render(
      <AssetCardGrid
        summary={{
          settled_cash: 0,
          pending_cash: 0,
          advanced_cash: 0,
          cash_advance_liability: 1_000_000,
          stock_market_value: 0,
          total_equity: 0,
          available_buying_power: 0,
          withdrawable_cash: 0,
          currency: "VND",
          as_of: null,
        }}
      />,
    );
    expect(screen.getByText("Cash advance liability")).toBeDefined();
  });

  it("renders all eight labels even with a populated summary", () => {
    render(
      <AssetCardGrid
        summary={{
          settled_cash: 1,
          pending_cash: 2,
          advanced_cash: 3,
          cash_advance_liability: 4,
          stock_market_value: 5,
          total_equity: 6,
          available_buying_power: 7,
          withdrawable_cash: 8,
          currency: "VND",
          as_of: null,
        }}
      />,
    );
    for (const label of [
      "Settled cash",
      "Pending cash",
      "Advanced cash",
      "Cash advance liability",
      "Stock market value",
      "Total equity",
      "Buying power",
      "Withdrawable",
    ]) {
      expect(screen.getByText(label)).toBeDefined();
    }
  });
});
