import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { PnlWaterfall } from "./PnlWaterfall";

describe("PnlWaterfall", () => {
  it("renders an empty state when given no buckets", () => {
    render(<PnlWaterfall data={[]} />);
    expect(screen.getByText(/No PnL breakdown yet/)).toBeDefined();
  });

  it("renders the chart container when given buckets", () => {
    const data = [
      { bucket: "Realized", value: 1_200_000 },
      { bucket: "Unrealized", value: 2_000_000 },
      { bucket: "Costs", value: -180_000 },
      { bucket: "Net", value: 3_020_000 },
    ];
    const { container } = render(<PnlWaterfall data={data} />);
    expect(container.querySelector(".recharts-responsive-container")).not.toBeNull();
  });
});
