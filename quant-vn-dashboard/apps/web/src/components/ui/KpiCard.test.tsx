import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { KpiCard } from "./KpiCard";

describe("KpiCard", () => {
  it("renders label and value", () => {
    render(<KpiCard label="Total Equity" value="1.25B VND" />);
    expect(screen.getByText("Total Equity")).toBeDefined();
    expect(screen.getByText("1.25B VND")).toBeDefined();
  });

  it("renders the optional hint", () => {
    render(<KpiCard label="Net PnL" value="+75M VND" hint="settled + MtM" />);
    expect(screen.getByText("settled + MtM")).toBeDefined();
  });

  it("renders a skeleton while loading", () => {
    const { container } = render(<KpiCard label="Loading" value="hidden" loading />);
    expect(container.querySelector(".animate-pulse")).not.toBeNull();
    // The skeleton replaces the value, so the literal text should be absent.
    expect(screen.queryByText("hidden")).toBeNull();
  });
});
