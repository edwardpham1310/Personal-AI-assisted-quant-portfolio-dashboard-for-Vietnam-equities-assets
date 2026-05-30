import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { IndexCardGrid } from "./IndexCardGrid";
import { MOCK_INDICES } from "@/lib/mock/market";

describe("IndexCardGrid", () => {
  it("renders one card per index", () => {
    render(<IndexCardGrid indices={MOCK_INDICES} loading={false} />);
    for (const idx of MOCK_INDICES) {
      expect(screen.getByText(idx.code)).toBeDefined();
    }
  });

  it("renders skeletons while loading", () => {
    const { container } = render(<IndexCardGrid indices={MOCK_INDICES} loading={true} />);
    expect(container.querySelectorAll(".animate-pulse").length).toBeGreaterThan(0);
  });

  it("renders gracefully with an empty list", () => {
    const { container } = render(<IndexCardGrid indices={[]} loading={false} />);
    expect(container.querySelectorAll("p").length).toBe(0);
  });
});
