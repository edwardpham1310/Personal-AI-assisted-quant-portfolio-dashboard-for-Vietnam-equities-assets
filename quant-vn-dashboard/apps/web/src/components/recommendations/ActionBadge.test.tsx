import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { ActionBadge, RecoStatusBadge } from "./ActionBadge";
import type {
  RecommendationAction,
  RecommendationStatus,
} from "@/hooks/useRecommendations";

const ALL_ACTIONS: RecommendationAction[] = [
  "BUY_CANDIDATE",
  "WATCH",
  "HOLD",
  "REDUCE",
  "SELL_CANDIDATE",
  "AVOID",
  "REJECTED",
];

const ALL_STATUSES: RecommendationStatus[] = ["VALID", "WARNING", "REJECTED"];

describe("ActionBadge", () => {
  it("renders every action label with a research-only aria description", () => {
    for (const action of ALL_ACTIONS) {
      const { container, unmount } = render(<ActionBadge action={action} />);
      const badge = container.querySelector(`[data-action="${action}"]`);
      expect(badge).not.toBeNull();
      expect(badge?.getAttribute("aria-label")).toMatch(
        /research signal, not financial advice/i,
      );
      expect(
        container.textContent?.toLowerCase(),
      ).toContain("research signal · not advice");
      unmount();
    }
  });

  it("RejectedBadge label collapses BUY/SELL into research-only wording", () => {
    render(<ActionBadge action="REJECTED" />);
    const el = screen.getByText(/rejected/i);
    expect(el).toBeDefined();
  });
});

describe("RecoStatusBadge", () => {
  it("renders every recommendation status", () => {
    for (const status of ALL_STATUSES) {
      const { container, unmount } = render(<RecoStatusBadge status={status} />);
      const badge = container.querySelector(`[data-reco-status="${status}"]`);
      expect(badge).not.toBeNull();
      unmount();
    }
  });
});
