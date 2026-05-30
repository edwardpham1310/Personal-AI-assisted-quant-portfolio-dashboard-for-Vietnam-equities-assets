import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { EquityCurveChart } from "./EquityCurveChart";

describe("EquityCurveChart", () => {
  it("renders an empty state when given no data", () => {
    render(<EquityCurveChart data={[]} />);
    expect(screen.getByText(/No portfolio history yet/)).toBeDefined();
  });

  it("renders the chart container when given data", () => {
    const data = [
      { ts: "2026-01-01", equity: 1_000_000 },
      { ts: "2026-01-02", equity: 1_010_000 },
    ];
    const { container } = render(<EquityCurveChart data={data} />);
    // Recharts renders its SVG inside a ResponsiveContainer; presence of the
    // recharts class is enough to prove the chart mounted.
    expect(container.querySelector(".recharts-responsive-container")).not.toBeNull();
  });
});
