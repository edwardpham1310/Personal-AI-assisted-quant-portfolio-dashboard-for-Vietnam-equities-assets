import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";

// All hooks are mocked to avoid network calls and Supabase auth lookups.
const apiMock = vi.fn();

vi.mock("@/lib/api", () => ({
  useApi: () => apiMock,
  ApiError: class ApiError extends Error {},
}));

vi.mock("@/hooks/useScanner", async () => {
  const actual = await vi.importActual<typeof import("@/hooks/useScanner")>(
    "@/hooks/useScanner",
  );
  return {
    ...actual,
    useWatchlistScanner: () => ({
      results: [],
      loading: false,
      error: null,
      refresh: vi.fn(),
    }),
  };
});

vi.mock("@/hooks/useWatchlistStream", () => ({
  useWatchlistStream: () => ({
    quotes: [],
    lastUpdate: null,
    connected: false,
    error: null,
  }),
}));

import WatchlistPage from "./page";

beforeEach(() => {
  apiMock.mockReset();
});

describe("WatchlistPage", () => {
  it("renders the page header and disclaimer copy", async () => {
    apiMock.mockResolvedValueOnce([]);
    render(<WatchlistPage />);

    expect(screen.getByRole("heading", { name: "Watchlist" })).toBeDefined();
    await waitFor(() => {
      expect(
        screen.getByText(/Research signals · not financial advice/i),
      ).toBeDefined();
    });
  });

  it("shows the empty state when the user has no watchlists", async () => {
    apiMock.mockResolvedValueOnce([]);
    render(<WatchlistPage />);

    await waitFor(() => {
      expect(screen.getByText("No watchlists yet")).toBeDefined();
    });
    expect(screen.getByText(/Create one above/i)).toBeDefined();
  });

  it("shows the empty watchlist hint when a list has no symbols", async () => {
    apiMock.mockResolvedValueOnce([
      {
        id: "wl-1",
        user_id: "user-1",
        name: "Core VN30",
        description: null,
        items: [],
      },
    ]);
    render(<WatchlistPage />);

    await waitFor(() => {
      expect(screen.getByText(/Add a symbol to see signals/i)).toBeDefined();
    });
  });

  it("renders a selector when more than one watchlist exists", async () => {
    apiMock.mockResolvedValueOnce([
      {
        id: "wl-1",
        user_id: "user-1",
        name: "Core VN30",
        description: null,
        items: [],
      },
      {
        id: "wl-2",
        user_id: "user-1",
        name: "Banks",
        description: null,
        items: [],
      },
    ]);
    render(<WatchlistPage />);

    await waitFor(() => {
      expect(
        screen.getByRole("combobox", { name: /Select watchlist/i }),
      ).toBeDefined();
    });
  });
});
