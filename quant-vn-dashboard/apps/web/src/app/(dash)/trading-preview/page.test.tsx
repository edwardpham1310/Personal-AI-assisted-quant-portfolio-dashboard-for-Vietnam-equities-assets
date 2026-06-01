import { describe, expect, it, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import TradingPreviewPage from "./page";

// ── Mock the API ─────────────────────────────────────────────────────────
// The mock returns the SAME function reference across calls so React's
// useCallback deps don't churn each render — otherwise useEffect fires
// infinitely.

const apiCalls: Array<{ path: string; init?: RequestInit }> = [];
// Switch the mock between VALID and REJECTED responses without
// rebuilding the entire mock — test toggles this flag before submitting.
const mockState = { previewRejected: false };

const stableApiFn = async (path: string, init?: RequestInit) => {
  apiCalls.push({ path, init });
  if (path === "/trading") {
    return [
      {
        id: "acc-1",
        user_id: "user-1",
        broker: "SSI",
        account_number_masked: "****7890",
        account_alias: "Main",
        read_only_enabled: true,
        trading_enabled: false,
        created_at: null,
        updated_at: null,
      },
    ];
  }
  if (path.startsWith("/trading/cash")) {
    return {
      account_id: "acc-1",
      cash_balance: 50_000_000,
      buying_power: 48_500_000,
      withdrawable_cash: 30_000_000,
      pending_cash: 1_500_000,
      currency: "VND",
      as_of: "2026-05-31T00:00:00Z",
    };
  }
  if (path.startsWith("/trading/positions")) {
    return [
      {
        account_id: "acc-1",
        symbol: "FPT",
        exchange: "HOSE",
        quantity: 200,
        sellable_quantity: 200,
        pending_quantity: 0,
        avg_cost: 80000,
        market_price: 86000,
        market_value: 17_200_000,
        unrealized_pnl: 1_200_000,
        as_of: "2026-05-31T00:00:00Z",
      },
    ];
  }
  if (path === "/trading/order-preview") {
    const body = JSON.parse(init?.body as string);
    if (mockState.previewRejected) {
      return {
        symbol: body.symbol,
        side: body.side,
        quantity: body.quantity,
        order_type: body.order_type,
        limit_price: body.limit_price,
        estimated_value: 11_782_000,
        estimated_fees: 17_673,
        estimated_tax: 0,
        estimated_vat: 1_767,
        estimated_slippage: 11_782,
        total_cash_required: 11_813_222,
        net_sell_proceeds: null,
        settlement_date: "2026-06-02",
        validation_status: "REJECTED",
        warnings: [],
        rejection_reasons: [
          "LOT_SIZE_VIOLATION: quantity must be a multiple of 100",
          "INSUFFICIENT_CASH: required=11813222 available=5000000",
        ],
        is_live_order_submission_enabled: false,
      };
    }
    return {
      symbol: body.symbol,
      side: body.side,
      quantity: body.quantity,
      order_type: body.order_type,
      limit_price: body.limit_price,
      estimated_value: 12_500_000,
      estimated_fees: 18_750,
      estimated_tax: body.side === "SELL" ? 12_500 : 0,
      estimated_vat: 1_875,
      estimated_slippage: 12_500,
      total_cash_required: body.side === "BUY" ? 12_533_125 : null,
      net_sell_proceeds: body.side === "SELL" ? 12_454_375 : null,
      settlement_date: "2026-06-02",
      validation_status: "VALID",
      warnings: ["T+2_SETTLEMENT: sell proceeds settle on T+2"],
      rejection_reasons: [],
      is_live_order_submission_enabled: false,
    };
  }
  throw new Error(`unmocked path: ${path}`);
};

vi.mock("@/lib/api", () => {
  return {
    ApiError: class extends Error {
      status: number;
      detail: string;
      constructor(status: number, detail: string) {
        super(detail);
        this.status = status;
        this.detail = detail;
      }
    },
    // Returning the SAME function reference each render is critical —
    // otherwise hook deps churn and useEffect loops forever.
    useApi: () => stableApiFn,
  };
});

beforeEach(() => {
  apiCalls.length = 0;
  mockState.previewRejected = false;
});

describe("TradingPreviewPage", () => {
  it("renders the page with preview-only banner", async () => {
    render(<TradingPreviewPage />);
    expect(screen.getByTestId("trading-preview-page")).toBeDefined();
    expect(screen.getByTestId("phase-2-5-banner")).toBeDefined();
    await waitFor(() => expect(screen.getByTestId("account-selector")).toBeDefined());
  });

  it("renders cash + positions after account load", async () => {
    render(<TradingPreviewPage />);
    await waitFor(() => {
      expect(screen.getByTestId("cash-buying-power")).toBeDefined();
      expect(screen.getByTestId("positions-table")).toBeDefined();
    });
    expect(screen.getByTestId("cash-buying-power").textContent).toContain("48");
  });

  it("submits an order preview and renders structured result", async () => {
    render(<TradingPreviewPage />);
    await waitFor(() => screen.getByTestId("preview-form"));
    fireEvent.submit(screen.getByTestId("preview-form"));
    await waitFor(() => screen.getByTestId("preview-result"));
    expect(screen.getByTestId("result-total-cash")).toBeDefined();
    expect(screen.getByTestId("result-warnings")).toBeDefined();
    // Must include the disabled-submit placeholder.
    const submitBtn = screen.getByTestId("submit-real-order") as HTMLButtonElement;
    expect(submitBtn.disabled).toBe(true);
  });

  it("emits an API call to the order-preview endpoint with the form payload", async () => {
    render(<TradingPreviewPage />);
    await waitFor(() => screen.getByTestId("preview-form"));
    apiCalls.length = 0;
    fireEvent.submit(screen.getByTestId("preview-form"));
    await waitFor(() =>
      expect(apiCalls.some((c) => c.path === "/trading/order-preview")).toBe(true),
    );
    const previewCall = apiCalls.find((c) => c.path === "/trading/order-preview");
    expect(previewCall).toBeDefined();
    const body = JSON.parse(previewCall!.init!.body as string);
    expect(body.symbol).toBe("FPT");
    expect(body.side).toBe("BUY");
    expect(body.quantity).toBe(100);
  });

  it("never exposes a live submit button", async () => {
    render(<TradingPreviewPage />);
    await waitFor(() => screen.getByTestId("preview-form"));
    const submitBtn = screen.getByTestId("submit-real-order") as HTMLButtonElement;
    expect(submitBtn.disabled).toBe(true);
    expect(submitBtn.title).toMatch(/not enabled/i);
  });

  it("renders rejection reasons when backend rejects the preview", async () => {
    mockState.previewRejected = true;
    render(<TradingPreviewPage />);
    await waitFor(() => screen.getByTestId("preview-form"));
    fireEvent.submit(screen.getByTestId("preview-form"));
    await waitFor(() => screen.getByTestId("result-rejections"));
    const rejections = screen.getByTestId("result-rejections");
    expect(rejections.textContent).toContain("LOT_SIZE_VIOLATION");
    expect(rejections.textContent).toContain("INSUFFICIENT_CASH");
    // Submit-real-order button must STILL be disabled after a rejection.
    const submitBtn = screen.getByTestId("submit-real-order") as HTMLButtonElement;
    expect(submitBtn.disabled).toBe(true);
  });

  it("renders the T+2 warning text after a SELL preview", async () => {
    render(<TradingPreviewPage />);
    await waitFor(() => screen.getByTestId("preview-form"));
    // Switch to SELL side via the form select.
    const sideSelect = screen.getByTestId("input-side") as HTMLSelectElement;
    fireEvent.change(sideSelect, { target: { value: "SELL" } });
    fireEvent.submit(screen.getByTestId("preview-form"));
    await waitFor(() => screen.getByTestId("result-warnings"));
    expect(screen.getByTestId("result-warnings").textContent).toContain("T+2_SETTLEMENT");
  });
});
