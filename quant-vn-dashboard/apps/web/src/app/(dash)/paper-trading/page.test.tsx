import { describe, expect, it, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import PaperTradingPage from "./page";

// ── Mock the API (stable reference; see useTradingPreview test pattern) ──

const apiCalls: Array<{ path: string; init?: RequestInit }> = [];

const mockState: {
  accounts: { id: string; name: string }[];
  rejectNext: boolean;
} = { accounts: [{ id: "p1", name: "Main" }], rejectNext: false };

const stableApiFn = async (path: string, init?: RequestInit) => {
  apiCalls.push({ path, init });
  if (path === "/paper/accounts" && (!init || init.method !== "POST")) {
    return mockState.accounts.map((a) => ({
      id: a.id,
      user_id: "u1",
      name: a.name,
      starting_cash: 100_000_000,
      current_cash: 100_000_000,
      currency: "VND",
      created_at: "2026-05-31T00:00:00Z",
      updated_at: null,
    }));
  }
  if (path === "/paper/accounts" && init?.method === "POST") {
    const body = JSON.parse(init.body as string);
    const id = `p${mockState.accounts.length + 1}`;
    mockState.accounts.push({ id, name: body.name });
    return {
      id,
      user_id: "u1",
      name: body.name,
      starting_cash: body.starting_cash,
      current_cash: body.starting_cash,
      currency: body.currency || "VND",
      created_at: "2026-05-31T00:00:00Z",
      updated_at: null,
    };
  }
  if (path.endsWith("/summary")) {
    return {
      account: {
        id: "p1",
        user_id: "u1",
        name: "Main",
        starting_cash: 100_000_000,
        current_cash: 90_000_000,
        currency: "VND",
        created_at: null,
        updated_at: null,
      },
      cash: 90_000_000,
      pending_cash: 1_500_000,
      stock_value: 12_500_000,
      total_equity: 104_000_000,
      realized_pnl: 0,
      unrealized_pnl: 0,
      drawdown: 0,
      open_orders: 0,
      positions: [
        {
          id: "pos1",
          user_id: "u1",
          paper_account_id: "p1",
          symbol: "FPT",
          quantity: 100,
          sellable_quantity: 0,
          pending_quantity: 100,
          avg_cost: 86000,
          market_price: 86500,
          market_value: 8_650_000,
          unrealized_pnl: 50_000,
          updated_at: null,
        },
      ],
      data_status: "FRESH",
    };
  }
  if (path.endsWith("/positions")) return [];
  if (path.endsWith("/orders") && (!init || init.method !== "POST")) return [];
  if (path.endsWith("/fills")) return [];
  if (path.endsWith("/equity-curve")) {
    return [
      {
        id: "e1",
        paper_account_id: "p1",
        timestamp: "2026-05-31T00:00:00Z",
        cash: 100_000_000,
        pending_cash: 0,
        stock_value: 0,
        total_equity: 100_000_000,
        drawdown: 0,
      },
      {
        id: "e2",
        paper_account_id: "p1",
        timestamp: "2026-05-31T01:00:00Z",
        cash: 90_000_000,
        pending_cash: 1_500_000,
        stock_value: 12_500_000,
        total_equity: 104_000_000,
        drawdown: 0,
      },
    ];
  }
  if (path.includes("/orders") && init?.method === "POST") {
    if (mockState.rejectNext) {
      return {
        order: {
          id: "o2",
          paper_account_id: "p1",
          source_type: "MANUAL",
          source_id: null,
          symbol: "FPT",
          side: "BUY",
          order_type: "MARKET",
          quantity: 137,
          limit_price: null,
          status: "REJECTED",
          rejection_reason: "LOT_SIZE_VIOLATION_lot100",
          created_at: "2026-05-31T01:00:00Z",
        },
        fill: null,
        rejection_reason: "LOT_SIZE_VIOLATION_lot100",
      };
    }
    return {
      order: {
        id: "o1",
        paper_account_id: "p1",
        source_type: "MANUAL",
        source_id: null,
        symbol: "FPT",
        side: "BUY",
        order_type: "MARKET",
        quantity: 100,
        limit_price: null,
        status: "FILLED",
        rejection_reason: null,
        created_at: "2026-05-31T01:00:00Z",
      },
      fill: {
        id: "f1",
        paper_account_id: "p1",
        paper_order_id: "o1",
        symbol: "FPT",
        side: "BUY",
        quantity: 100,
        fill_price: 86000,
        gross_value: 8_600_000,
        brokerage_fee: 12_900,
        vat: 1_290,
        sell_tax: 0,
        slippage: 8_600,
        net_cash_impact: -8_622_790,
        filled_at: "2026-05-31T01:00:00Z",
      },
      rejection_reason: null,
    };
  }
  throw new Error(`unmocked: ${path}`);
};

vi.mock("@/lib/api", () => ({
  ApiError: class extends Error {
    constructor(public status: number, public detail: string) {
      super(detail);
    }
  },
  useApi: () => stableApiFn,
}));

beforeEach(() => {
  apiCalls.length = 0;
  mockState.accounts = [{ id: "p1", name: "Main" }];
  mockState.rejectNext = false;
});

describe("PaperTradingPage", () => {
  it("renders + shows the Phase 2.7 banner + selector", async () => {
    render(<PaperTradingPage />);
    expect(screen.getByTestId("paper-trading-page")).toBeDefined();
    expect(screen.getByTestId("phase-2-7-banner")).toBeDefined();
    await waitFor(() => {
      expect(screen.getByTestId("paper-account-selector")).toBeDefined();
    });
  });

  it("creates a new paper account via the form", async () => {
    render(<PaperTradingPage />);
    await waitFor(() => screen.getByTestId("create-account-form"));
    fireEvent.change(screen.getByTestId("new-account-name"), {
      target: { value: "Second" },
    });
    fireEvent.change(screen.getByTestId("new-account-cash"), {
      target: { value: "50000000" },
    });
    apiCalls.length = 0;
    fireEvent.submit(screen.getByTestId("create-account-form"));
    await waitFor(() =>
      expect(
        apiCalls.some(
          (c) => c.path === "/paper/accounts" && c.init?.method === "POST",
        ),
      ).toBe(true),
    );
    const createCall = apiCalls.find(
      (c) => c.path === "/paper/accounts" && c.init?.method === "POST",
    );
    const body = JSON.parse(createCall!.init!.body as string);
    expect(body.name).toBe("Second");
    expect(body.starting_cash).toBe(50_000_000);
  });

  it("renders positions + pending cash KPIs from summary", async () => {
    render(<PaperTradingPage />);
    await waitFor(() => screen.getByTestId("positions-table"));
    expect(screen.getByTestId("pending-cash").textContent).toContain("1");
    expect(screen.getByTestId("data-status").textContent).toContain("FRESH");
  });

  it("submits a paper order and renders the fill result", async () => {
    render(<PaperTradingPage />);
    await waitFor(() => screen.getByTestId("paper-order-form"));
    fireEvent.submit(screen.getByTestId("paper-order-form"));
    await waitFor(() => screen.getByTestId("paper-order-result"));
    expect(screen.getByTestId("paper-order-result").textContent).toContain(
      "FILLED",
    );
  });

  it("renders rejection reason on lot violation", async () => {
    mockState.rejectNext = true;
    render(<PaperTradingPage />);
    await waitFor(() => screen.getByTestId("paper-order-form"));
    fireEvent.submit(screen.getByTestId("paper-order-form"));
    await waitFor(() => screen.getByTestId("paper-order-result"));
    expect(screen.getByTestId("paper-order-result").textContent).toContain(
      "LOT_SIZE_VIOLATION",
    );
  });

  it("renders the equity chart container when curve has points", async () => {
    render(<PaperTradingPage />);
    await waitFor(() => screen.getByTestId("equity-chart"));
  });
});
