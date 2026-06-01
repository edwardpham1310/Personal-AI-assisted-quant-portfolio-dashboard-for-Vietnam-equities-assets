import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { PositionTable } from "./PositionTable";
import type { EnrichedPosition } from "@/hooks/portfolio-types";

function makePosition(overrides: Partial<EnrichedPosition>): EnrichedPosition {
  const base: EnrichedPosition = {
    id: "pos-1",
    account_id: "acc-1",
    symbol: "FPT",
    exchange: "HOSE",
    quantity: 1_000,
    sellable_quantity: 800,
    pending_quantity: 200,
    avg_cost: 120_000,
    market_price: 130_000,
    market_value: 130_000_000,
    unrealized_pnl: 10_000_000,
    unrealized_pnl_pct: 8.33,
    weight: 25,
    strategy_tag: "trend-follow",
    note: null,
    warnings: [],
    last_marked_at: new Date().toISOString(),
  };
  return { ...base, ...overrides };
}

describe("PositionTable", () => {
  it("renders an empty state when there are no rows", () => {
    render(<PositionTable rows={[]} />);
    expect(screen.getByText(/No positions yet/i)).toBeDefined();
    expect(screen.queryByRole("table")).toBeNull();
  });

  it("renders one tbody row per position", () => {
    const rows = [
      makePosition({ id: "1", symbol: "FPT" }),
      makePosition({ id: "2", symbol: "HPG", weight: 10 }),
    ];
    render(<PositionTable rows={rows} />);
    const tbody = screen.getByRole("table").querySelector("tbody")!;
    expect(within(tbody).getAllByRole("row").length).toBe(2);
    expect(screen.getByTestId("position-row-FPT")).toBeDefined();
    expect(screen.getByTestId("position-row-HPG")).toBeDefined();
  });

  it("sorts rows by symbol when the Symbol header is clicked", () => {
    const rows = [
      makePosition({ id: "1", symbol: "HPG" }),
      makePosition({ id: "2", symbol: "ACB" }),
      makePosition({ id: "3", symbol: "FPT" }),
    ];
    render(<PositionTable rows={rows} />);
    fireEvent.click(screen.getByRole("button", { name: /Symbol/ }));

    const bodyRows = screen.getByRole("table").querySelectorAll("tbody tr");
    const order = Array.from(bodyRows).map((r) =>
      r.getAttribute("data-testid")?.replace("position-row-", ""),
    );
    expect(order).toEqual(["ACB", "FPT", "HPG"]);
  });

  it("renders an em-dash and tooltip when market_price is null", () => {
    const rows = [
      makePosition({
        symbol: "FPT",
        market_price: null,
        market_value: null,
        unrealized_pnl: null,
        unrealized_pnl_pct: null,
        weight: null,
        warnings: ["Mark stale: no recent quote"],
      }),
    ];
    render(<PositionTable rows={rows} />);
    const row = screen.getByTestId("position-row-FPT");
    const dashes = within(row).getAllByText("—");
    expect(dashes.length).toBeGreaterThan(0);
    // The warning surfaces in the tooltip as the dash's aria-label.
    const dashWithWarning = dashes.find(
      (el) => el.getAttribute("aria-label") === "Mark stale: no recent quote",
    );
    expect(dashWithWarning).toBeDefined();
  });

  it("wires edit + delete callbacks per row", () => {
    const rows = [makePosition({ symbol: "FPT" })];
    const onEdit = vi.fn();
    const onDelete = vi.fn();
    render(<PositionTable rows={rows} onEdit={onEdit} onDelete={onDelete} />);

    fireEvent.click(screen.getByRole("button", { name: /Edit FPT/ }));
    fireEvent.click(screen.getByRole("button", { name: /Delete FPT/ }));
    expect(onEdit).toHaveBeenCalledTimes(1);
    expect(onDelete).toHaveBeenCalledTimes(1);
  });
});
