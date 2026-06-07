import { describe, expect, it } from "vitest";
import { render } from "@testing-library/react";
import { MarketBreadthCard } from "./MarketBreadthCard";
import type { MarketBreadth } from "@/lib/mock/market";

describe("MarketBreadthCard", () => {
  it("renders a full payload without NaN", () => {
    const breadth: MarketBreadth = {
      advancers: 12,
      decliners: 8,
      unchanged: 2,
      ceiling: 1,
      floor: 0,
    };
    const { container } = render(<MarketBreadthCard breadth={breadth} isMock={false} />);
    expect(container.textContent).not.toContain("NaN");
    // 12 / (12+8+2) ≈ 55%
    expect(container.querySelector('[aria-label="Advancers 55%"]')).not.toBeNull();
  });

  it("labels coverage honestly: tracked universe by default, full market when confirmed", () => {
    const base = { advancers: 1, decliners: 1, unchanged: 1, ceiling: 0, floor: 0 };

    const tracked = render(
      <MarketBreadthCard
        breadth={{ ...base, coverage: "tracked_universe", universe_size: 6 }}
        isMock={false}
      />,
    );
    expect(tracked.container.textContent).toContain("Tracked universe");
    expect(tracked.container.textContent).not.toContain("Full market");

    const full = render(
      <MarketBreadthCard
        breadth={{ ...base, coverage: "full_market", universe_size: 420 }}
        isMock={false}
      />,
    );
    expect(full.container.textContent).toContain("Full market");
    expect(full.container.textContent).toContain("420");
  });

  it("does not render NaN on a sparse/partial payload", () => {
    // A cold-cache or malformed payload missing fields must coerce to 0, not NaN.
    const partial = { advancers: 3 } as unknown as MarketBreadth;
    const { container } = render(<MarketBreadthCard breadth={partial} isMock={false} />);
    expect(container.textContent).not.toContain("NaN");
    // advancers 3 / total 3 => 100%
    expect(container.querySelector('[aria-label="Advancers 100%"]')).not.toBeNull();
  });

  it("does not crash and shows 0% on an all-empty payload", () => {
    const empty = {} as unknown as MarketBreadth;
    const { container } = render(<MarketBreadthCard breadth={empty} isMock={false} />);
    expect(container.textContent).not.toContain("NaN");
    expect(container.querySelector('[aria-label="Advancers 0%"]')).not.toBeNull();
  });
});
