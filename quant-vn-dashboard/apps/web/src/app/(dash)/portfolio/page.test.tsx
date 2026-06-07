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

type Account = { id: string; user_id: string; name: string; broker: string; currency: string };

// Route the api mock by path: PortfolioPage calls /portfolio/manual to discover
// accounts; BrokerAccountCard calls POST /portfolio/sync/ssi; the
// Portfolio-vs-VNINDEX chart fetches the equity curve + VNINDEX. Default the
// broker snapshot to mock mode so no live balances are fetched.
function setupApi(opts: { accounts?: Account[]; broker?: Record<string, unknown> } = {}) {
  const accounts = opts.accounts ?? [];
  const broker = opts.broker ?? { connected: false, status_code: "READ_ONLY", mock: true };
  apiMock.mockImplementation((path?: string) => {
    if (typeof path !== "string") return Promise.resolve(undefined);
    if (path.startsWith("/portfolio/sync/ssi")) return Promise.resolve(broker);
    if (path.startsWith("/portfolio/manual")) return Promise.resolve({ accounts });
    if (path.startsWith("/portfolio/equity-curve")) return Promise.resolve([]);
    if (path.startsWith("/market/ohlcv/daily/VNINDEX")) return Promise.resolve([]);
    return Promise.resolve(undefined);
  });
}

beforeEach(() => {
  apiMock.mockReset();
  summaryRefresh.mockReset();
  positionsRefresh.mockReset();
});

describe("PortfolioPage", () => {
  it("renders the header and research disclaimer", async () => {
    setupApi();
    render(<PortfolioPage />);
    expect(screen.getByRole("heading", { name: "Portfolio" })).toBeDefined();
    expect(screen.getByText(/Research dashboard · Manual entry · No orders placed/i)).toBeDefined();
    // Drain the resolved fetches so post-fetch state updates land in the test.
    await waitFor(() => expect(apiMock).toHaveBeenCalled());
  });

  it("shows the no-account hint when the user has no accounts yet", async () => {
    setupApi({ accounts: [] });
    render(<PortfolioPage />);
    await waitFor(() => {
      expect(screen.getByText(/No account yet/i)).toBeDefined();
    });
  });

  it("shows the default-account notice when exactly one account exists", async () => {
    setupApi({
      accounts: [
        { id: "acc-1", user_id: "user-1", name: "Main SSI", broker: "SSI", currency: "VND" },
      ],
    });
    render(<PortfolioPage />);
    await waitFor(() => {
      expect(screen.getByText("Main SSI")).toBeDefined();
    });
    // The default-account notice appears next to the account name.
    expect(screen.getAllByText(/default account/i).length).toBeGreaterThan(0);
  });

  it("renders the broker card in honest mock state (no fake balances)", async () => {
    setupApi({ accounts: [] });
    render(<PortfolioPage />);
    await waitFor(() => {
      expect(screen.getByText(/running in mock mode/i)).toBeDefined();
    });
  });

  it("renders the position-table empty state when there are no positions", async () => {
    setupApi({ accounts: [] });
    render(<PortfolioPage />);
    await waitFor(() => {
      expect(screen.getByText(/No positions yet/i)).toBeDefined();
    });
    await waitFor(() => expect(apiMock).toHaveBeenCalled());
  });
});
