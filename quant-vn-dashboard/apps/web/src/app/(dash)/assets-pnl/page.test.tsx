import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, within } from "@testing-library/react";

const apiMock = vi.fn();
vi.mock("@/lib/api", () => ({
  useApi: () => apiMock,
  ApiError: class ApiError extends Error {},
}));

vi.mock("@/hooks/useAssetsSummary", () => ({
  useAssetsSummary: () => ({
    summary: {
      settled_cash: 0,
      pending_cash: 0,
      advanced_cash: 0,
      cash_advance_liability: 0,
      stock_market_value: 0,
      total_equity: 0,
      available_buying_power: 0,
      withdrawable_cash: 0,
      currency: "VND",
      as_of: null,
    },
    loading: false,
    error: null,
    refresh: vi.fn(),
  }),
}));

vi.mock("@/hooks/useAssetsPnl", () => ({
  useAssetsPnl: () => ({
    pnl: { realized: 0, unrealized: 0, total: 0, by_symbol: [] },
    loading: false,
    error: null,
    refresh: vi.fn(),
  }),
}));

vi.mock("@/hooks/useAssetsCosts", () => ({
  useAssetsCosts: () => ({
    costs: {
      brokerage_fee: 0,
      vat: 0,
      sell_tax: 0,
      cash_advance_fee: 0,
      slippage_estimate: 0,
      total: 0,
      period: "MTD" as const,
    },
    loading: false,
    error: null,
    refresh: vi.fn(),
  }),
}));

import AssetsPnlPage from "./page";

beforeEach(() => {
  apiMock.mockReset();
});

describe("AssetsPnlPage", () => {
  it("renders the page header and disclaimer", () => {
    render(<AssetsPnlPage />);
    expect(screen.getByRole("heading", { name: "Assets & PnL" })).toBeDefined();
    expect(
      screen.getByText(/Research dashboard · Manual entry · No orders placed/i),
    ).toBeDefined();
  });

  it("renders the 8-card asset grid with mocked zeros", () => {
    render(<AssetsPnlPage />);
    const grid = screen.getByTestId("asset-card-grid");
    expect(grid.querySelectorAll("p.uppercase").length).toBe(8);
    expect(within(grid).getAllByText("0 VND").length).toBe(8);
  });

  it("renders the period selector with MTD active by default", () => {
    render(<AssetsPnlPage />);
    const mtd = screen.getByRole("tab", { name: "MTD" });
    expect(mtd.getAttribute("aria-selected")).toBe("true");
    expect(screen.getByRole("tab", { name: "YTD" })).toBeDefined();
    expect(screen.getByRole("tab", { name: "ALL" })).toBeDefined();
  });

  it("renders the placeholder cards for net-worth, cash, and settlement alerts", () => {
    render(<AssetsPnlPage />);
    expect(screen.getByText("Net-worth curve")).toBeDefined();
    expect(screen.getByText("Cash movement")).toBeDefined();
    expect(screen.getByText("Settlement alerts")).toBeDefined();
  });
});
