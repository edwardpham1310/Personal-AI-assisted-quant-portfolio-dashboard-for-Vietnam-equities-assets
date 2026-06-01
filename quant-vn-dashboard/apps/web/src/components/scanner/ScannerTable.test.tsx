import { describe, expect, it } from "vitest";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { ScannerTable, type ScannerRow } from "./ScannerTable";
import type { ScannerResult } from "@/hooks/useScanner";

function makeResult(overrides: Partial<ScannerResult>): ScannerRow {
  const base: ScannerResult = {
    symbol: "FPT",
    last_price: 120_000,
    trend: "UPTREND",
    signals: ["MA20_ABOVE_MA50", "PRICE_ABOVE_MA20"],
    scores: { trend: 80, momentum: 60, volume: 50, liquidity: 70, risk: 30 },
    status: "BUY_CANDIDATE",
    warnings: [],
    as_of: new Date().toISOString(),
    indicators: {
      ma20: 119_000,
      ma50: 115_000,
      rsi14: 62,
      atr14: 1500,
      volume_ratio_20d: 1.4,
      high_20d: 122_000,
      high_55d: 125_000,
      avg_value_20d: 800_000_000,
    },
  };
  return { ...base, ...overrides };
}

describe("ScannerTable", () => {
  it("renders the empty state with no rows", () => {
    render(<ScannerTable rows={[]} />);
    expect(screen.getByText(/Add a symbol/i)).toBeDefined();
    // Sortable headers should not appear when the table is empty.
    expect(screen.queryByRole("table")).toBeNull();
  });

  it("renders one tbody row per result", () => {
    const rows: ScannerRow[] = [
      makeResult({ symbol: "FPT" }),
      makeResult({ symbol: "HPG", trend: "DOWNTREND", status: "AVOID" }),
    ];
    render(<ScannerTable rows={rows} />);
    const table = screen.getByRole("table");
    const tbody = table.querySelector("tbody")!;
    expect(within(tbody).getAllByRole("row").length).toBe(2);
    expect(screen.getByTestId("scanner-row-FPT")).toBeDefined();
    expect(screen.getByTestId("scanner-row-HPG")).toBeDefined();
  });

  it("sorts rows when the Trend score header is clicked", () => {
    const rows: ScannerRow[] = [
      makeResult({
        symbol: "LOW",
        scores: { trend: 10, momentum: 50, volume: 50, liquidity: 50, risk: 50 },
      }),
      makeResult({
        symbol: "HIGH",
        scores: { trend: 90, momentum: 50, volume: 50, liquidity: 50, risk: 50 },
      }),
      makeResult({
        symbol: "MID",
        scores: { trend: 50, momentum: 50, volume: 50, liquidity: 50, risk: 50 },
      }),
    ];
    render(<ScannerTable rows={rows} />);

    // First click on the score-column "Trend" header — there are two headers
    // labelled "Trend" (categorical + score), the second is the sortable score.
    const trendHeaders = screen.getAllByRole("button", { name: /^Trend/ });
    fireEvent.click(trendHeaders[trendHeaders.length - 1]);

    const bodyRows = screen.getByRole("table").querySelectorAll("tbody tr");
    const order = Array.from(bodyRows).map((r) =>
      r.getAttribute("data-testid")?.replace("scanner-row-", ""),
    );
    // Default direction for score columns is desc: highest first.
    expect(order).toEqual(["HIGH", "MID", "LOW"]);
  });

  it("filters rows when a signal chip is toggled", () => {
    const rows: ScannerRow[] = [
      makeResult({ symbol: "AAA", signals: ["MA20_ABOVE_MA50"] }),
      makeResult({ symbol: "BBB", signals: ["VOLUME_SPIKE"] }),
      makeResult({
        symbol: "CCC",
        signals: ["MA20_ABOVE_MA50", "VOLUME_SPIKE"],
      }),
    ];
    render(<ScannerTable rows={rows} />);

    // Click the "Vol spike" filter chip.
    const chip = screen.getByRole("button", { name: "Vol spike" });
    fireEvent.click(chip);

    const tbody = screen.getByRole("table").querySelector("tbody")!;
    const order = Array.from(tbody.querySelectorAll("tr")).map((r) =>
      r.getAttribute("data-testid")?.replace("scanner-row-", ""),
    );
    expect(order.sort()).toEqual(["BBB", "CCC"]);
  });

  it("shows a Stale badge when as_of is older than 5 minutes", () => {
    const stale = makeResult({
      symbol: "OLD",
      as_of: new Date(Date.now() - 10 * 60 * 1000).toISOString(),
    });
    const fresh = makeResult({ symbol: "NEW" });
    render(<ScannerTable rows={[stale, fresh]} />);

    const staleRow = screen.getByTestId("scanner-row-OLD");
    const freshRow = screen.getByTestId("scanner-row-NEW");
    expect(within(staleRow).getByText("Stale")).toBeDefined();
    expect(within(freshRow).queryByText("Stale")).toBeNull();
  });

  it("calls onRemove with the row symbol when the remove button is clicked", () => {
    const rows: ScannerRow[] = [makeResult({ symbol: "FPT" })];
    const removed: string[] = [];
    render(<ScannerTable rows={rows} onRemove={(s) => removed.push(s)} />);
    fireEvent.click(screen.getByRole("button", { name: /Remove FPT/ }));
    expect(removed).toEqual(["FPT"]);
  });
});
