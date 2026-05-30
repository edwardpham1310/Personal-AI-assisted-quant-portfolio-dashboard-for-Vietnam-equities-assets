import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";

// All network-touching hooks are mocked. The api mock handles the
// "/portfolio/manual" call that PortfolioPage uses to discover accounts.
const apiMock = vi.fn();

vi.mock("@/lib/api", () => ({
  useApi: () => apiMock,
  ApiError: class ApiError extends Error {},
}));

const summaryRefresh = vi.fn();
const positionsRefresh = vi.fn();

vi.mock("@/hooks/usePortfolioSummary", () => ({
  usePortfolioSummary: () => ({
    summary: null,
    loading: false,
    error: null,
    refresh: summaryRefresh,
  }),
}));

vi.mock("@/hooks/usePortfolioPositions", () => ({
  usePortfolioPositions: () => ({
    positions: [],
    loading: false,
    error: null,
    refresh: positionsRefresh,
  }),
}));

import PortfolioPage from "./page";

beforeEach(() => {
  apiMock.mockReset();
  summaryRefresh.mockReset();
  positionsRefresh.mockReset();
});

describe("PortfolioPage", () => {
  it("renders the header and research disclaimer", async () => {
    apiMock.mockResolvedValueOnce({ accounts: [] });
    render(<PortfolioPage />);
    expect(screen.getByRole("heading", { name: "Portfolio" })).toBeDefined();
    expect(
      screen.getByText(/Research dashboard · Manual entry · No orders placed/i),
    ).toBeDefined();
    // Drain the resolved /portfolio/manual promise so the post-fetch state
    // update lands inside the test (silences React act() warnings).
    await waitFor(() => expect(apiMock).toHaveBeenCalled());
  });

  it("shows the no-account hint when the user has no accounts yet", async () => {
    apiMock.mockResolvedValueOnce({ accounts: [] });
    render(<PortfolioPage />);
    await waitFor(() => {
      expect(screen.getByText(/No account yet/i)).toBeDefined();
    });
  });

  it("shows the default-account notice when exactly one account exists", async () => {
    apiMock.mockResolvedValueOnce({
      accounts: [
        {
          id: "acc-1",
          user_id: "user-1",
          name: "Main SSI",
          broker: "SSI",
          currency: "VND",
        },
      ],
    });
    render(<PortfolioPage />);
    await waitFor(() => {
      expect(screen.getByText("Main SSI")).toBeDefined();
    });
    // The default-account notice appears next to the account name.
    expect(screen.getAllByText(/default account/i).length).toBeGreaterThan(0);
  });

  it("renders the disabled SSI sync button with a Phase 2 badge", async () => {
    apiMock.mockResolvedValueOnce({ accounts: [] });
    render(<PortfolioPage />);
    const btn = screen.getByRole("button", { name: /Sync from SSI/i });
    expect(btn).toBeDefined();
    expect(btn.hasAttribute("disabled")).toBe(true);
    expect(screen.getByText("Phase 2")).toBeDefined();
    await waitFor(() => expect(apiMock).toHaveBeenCalled());
  });

  it("renders the position-table empty state when there are no positions", async () => {
    apiMock.mockResolvedValueOnce({ accounts: [] });
    render(<PortfolioPage />);
    await waitFor(() => {
      expect(screen.getByText(/No positions yet/i)).toBeDefined();
    });
    await waitFor(() => expect(apiMock).toHaveBeenCalled());
  });
});
