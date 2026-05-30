import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { SignalBadge, SignalBadgeList, SIGNAL_META } from "./SignalBadge";
import type { SignalCode } from "@/hooks/useScanner";

const ALL: SignalCode[] = [
  "MA20_ABOVE_MA50",
  "PRICE_ABOVE_MA20",
  "VOLUME_SPIKE",
  "BREAKOUT_20D",
  "BREAKOUT_55D",
  "RSI_OVERBOUGHT",
  "RSI_OVERSOLD",
  "LOW_LIQUIDITY",
];

describe("SignalBadge", () => {
  it("renders the correct label for each signal code", () => {
    for (const code of ALL) {
      const { container, unmount } = render(<SignalBadge code={code} />);
      const node = container.querySelector(`[data-signal="${code}"]`);
      expect(node).not.toBeNull();
      expect(node?.textContent).toBe(SIGNAL_META[code].label);
      // Tooltip text is exposed via title attribute for hover info.
      expect(node?.getAttribute("title")).toBe(SIGNAL_META[code].description);
      // Aria-label gives screen readers the same context.
      expect(node?.getAttribute("aria-label")).toContain(SIGNAL_META[code].label);
      unmount();
    }
  });

  it("never mentions advice copy in description text", () => {
    for (const code of ALL) {
      const desc = SIGNAL_META[code].description.toLowerCase();
      expect(desc).not.toMatch(/\b(buy|sell|enter|exit)\b/);
    }
  });
});

describe("SignalBadgeList", () => {
  it("renders an em dash placeholder when empty", () => {
    render(<SignalBadgeList codes={[]} />);
    expect(screen.getByText("—")).toBeDefined();
  });

  it("renders one badge per code", () => {
    const codes: SignalCode[] = ["MA20_ABOVE_MA50", "VOLUME_SPIKE"];
    const { container } = render(<SignalBadgeList codes={codes} />);
    expect(container.querySelectorAll("[data-signal]").length).toBe(2);
  });
});
