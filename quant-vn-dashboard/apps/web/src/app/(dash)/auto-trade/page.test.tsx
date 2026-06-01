import { describe, expect, it, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import AutoTradePage from "./page";

const apiCalls: Array<{ path: string; init?: RequestInit }> = [];

const mockState: {
  mode: "OFF" | "PAPER_ONLY" | "LIVE_MANUAL_CONFIRM" | "LIVE_AUTO";
  liveValid: boolean;
  rejectManualConfirmWithReauth: boolean;
} = { mode: "OFF", liveValid: true, rejectManualConfirmWithReauth: false };

// Stable api function — see useTradingPreview test for the same pattern.
const stableApiFn = async (path: string, init?: RequestInit) => {
  apiCalls.push({ path, init });
  // Phase 2.9 engine endpoints — return empty arrays by default; tests
  // that exercise the engine extend this via mockState if needed.
  if (path.startsWith("/auto-trade/runs")) {
    if (init?.method === "POST") {
      return {
        id: "run-1",
        user_id: "u1",
        account_id: "acc-1",
        mode: "PAPER_ONLY",
        strategy_id: "default",
        status: path.includes("/stop") ? "STOPPED" : path.includes("/pause") ? "PAUSED" : "RUNNING",
        started_at: "2026-05-31T00:00:00Z",
        stopped_at: null,
        metadata: {},
      };
    }
    return [];
  }
  if (path.startsWith("/auto-trade/decisions")) return [];
  if (path.startsWith("/auto-trade/orders")) return [];
  if (path.startsWith("/auto-trade/risk-counters")) return [];
  if (path === "/trading") {
    return [
      {
        id: "acc-1",
        user_id: "user-1",
        broker: "SSI",
        account_number_masked: "****1234",
        account_alias: "Main",
        read_only_enabled: true,
        trading_enabled: false,
        created_at: null,
        updated_at: null,
      },
    ];
  }
  if (path.startsWith("/auto-trade/settings")) {
    if (init?.method === "PUT") {
      const body = JSON.parse(init.body as string);
      return {
        id: "s-1",
        user_id: "user-1",
        account_id: "acc-1",
        mode: mockState.mode,
        enabled: mockState.mode !== "OFF",
        max_capital_vnd: body.max_capital_vnd ?? 0,
        max_order_value_vnd: body.max_order_value_vnd ?? 0,
        max_orders_per_day: body.max_orders_per_day ?? 0,
        max_daily_loss_vnd: body.max_daily_loss_vnd ?? 0,
        max_position_weight: body.max_position_weight ?? 0,
        max_sector_weight: body.max_sector_weight ?? 0,
        allowed_strategies: body.allowed_strategies ?? [],
        allowed_symbols: body.allowed_symbols ?? [],
        allowed_watchlists: [],
        require_manual_confirm: true,
        require_reauth: true,
        last_reauth_at: null,
        risk_acknowledged_at: null,
        created_at: null,
        updated_at: null,
      };
    }
    return {
      id: "s-1",
      user_id: "user-1",
      account_id: "acc-1",
      mode: mockState.mode,
      enabled: mockState.mode !== "OFF",
      max_capital_vnd: 0,
      max_order_value_vnd: 0,
      max_orders_per_day: 0,
      max_daily_loss_vnd: 0,
      max_position_weight: 0,
      max_sector_weight: 0,
      allowed_strategies: [],
      allowed_symbols: [],
      allowed_watchlists: [],
      require_manual_confirm: true,
      require_reauth: true,
      last_reauth_at: null,
      risk_acknowledged_at: null,
      created_at: null,
      updated_at: null,
    };
  }
  if (path.startsWith("/auto-trade/state")) {
    return {
      id: "st-1",
      user_id: "user-1",
      account_id: "acc-1",
      mode: mockState.mode,
      is_running: false,
      last_started_at: null,
      last_stopped_at: null,
      emergency_stopped_at: null,
      emergency_stop_reason: null,
    };
  }
  if (path === "/auto-trade/enable-manual-confirm") {
    if (mockState.rejectManualConfirmWithReauth) {
      return {
        account_id: "acc-1",
        mode: "OFF",
        validation_status: "REJECTED",
        rejection_reasons: ["REAUTH_REQUIRED: please re-enter your password"],
        is_live_execution_enabled: false,
        last_reauth_at: null,
        risk_acknowledged_at: null,
      };
    }
    mockState.mode = "LIVE_MANUAL_CONFIRM";
    return {
      account_id: "acc-1",
      mode: "LIVE_MANUAL_CONFIRM",
      validation_status: "VALID",
      rejection_reasons: [],
      is_live_execution_enabled: false,
      last_reauth_at: null,
      risk_acknowledged_at: null,
    };
  }
  if (path.startsWith("/auto-trade/reauth")) {
    return { ok: true, last_reauth_at: "2026-05-31T00:00:00Z", valid_for_seconds: 300 };
  }
  if (path === "/auto-trade/enable-paper") {
    mockState.mode = "PAPER_ONLY";
    return {
      account_id: "acc-1",
      mode: "PAPER_ONLY",
      validation_status: "VALID",
      rejection_reasons: [],
      is_live_execution_enabled: false,
      last_reauth_at: null,
      risk_acknowledged_at: null,
    };
  }
  if (path === "/auto-trade/request-live-auto-enable") {
    if (mockState.liveValid) {
      return {
        account_id: "acc-1",
        mode: "OFF",
        validation_status: "VALID",
        rejection_reasons: [],
        is_live_execution_enabled: false,
        last_reauth_at: null,
        risk_acknowledged_at: null,
        next_step: "CONFIRM_RISK_ACKNOWLEDGEMENT",
      };
    }
    return {
      account_id: "acc-1",
      mode: "OFF",
      validation_status: "REJECTED",
      rejection_reasons: ["MAX_CAPITAL_VND_REQUIRED", "ALLOWED_STRATEGIES_REQUIRED"],
      is_live_execution_enabled: false,
      last_reauth_at: null,
      risk_acknowledged_at: null,
      next_step: "ABORT",
    };
  }
  if (path === "/auto-trade/confirm-live-auto-enable") {
    const body = JSON.parse(init?.body as string);
    if (!body.risk_acknowledged) {
      return {
        account_id: "acc-1",
        mode: "OFF",
        validation_status: "REJECTED",
        rejection_reasons: ["RISK_ACKNOWLEDGEMENT_REQUIRED"],
        is_live_execution_enabled: false,
        last_reauth_at: null,
        risk_acknowledged_at: null,
      };
    }
    mockState.mode = "LIVE_AUTO";
    return {
      account_id: "acc-1",
      mode: "LIVE_AUTO",
      validation_status: "VALID",
      rejection_reasons: [],
      is_live_execution_enabled: false,
      last_reauth_at: "2026-05-31T00:00:00Z",
      risk_acknowledged_at: "2026-05-31T00:00:00Z",
    };
  }
  if (path === "/auto-trade/disable") {
    mockState.mode = "OFF";
    return {
      account_id: "acc-1",
      mode: "OFF",
      validation_status: "VALID",
      rejection_reasons: [],
      is_live_execution_enabled: false,
      last_reauth_at: null,
      risk_acknowledged_at: null,
    };
  }
  if (path === "/auto-trade/emergency-stop") {
    mockState.mode = "OFF";
    return {
      account_id: "acc-1",
      mode: "OFF",
      validation_status: "VALID",
      rejection_reasons: [],
      is_live_execution_enabled: false,
      last_reauth_at: null,
      risk_acknowledged_at: null,
    };
  }
  if (path.startsWith("/auto-trade/audit-logs")) {
    return [
      {
        id: "a-1",
        user_id: "user-1",
        account_id: "acc-1",
        action: "AUTO_TRADE_ENABLE_PAPER",
        metadata: {},
        created_at: "2026-05-31T00:00:00Z",
      },
    ];
  }
  throw new Error(`unmocked path: ${path}`);
};

vi.mock("@/lib/api", () => ({
  ApiError: class extends Error {
    constructor(
      public status: number,
      public detail: string,
    ) {
      super(detail);
    }
  },
  useApi: () => stableApiFn,
}));

vi.mock("@/lib/supabase/client", () => ({
  createClient: () => ({
    auth: {
      signInWithPassword: async () => ({ data: null, error: null }),
      getSession: async () => ({ data: { session: null }, error: null }),
    },
  }),
}));

beforeEach(() => {
  apiCalls.length = 0;
  mockState.mode = "OFF";
  mockState.liveValid = true;
  mockState.rejectManualConfirmWithReauth = false;
});

describe("AutoTradePage", () => {
  it("renders the page with the research/safety banner and account selector", async () => {
    render(<AutoTradePage />);
    expect(screen.getByTestId("auto-trade-page")).toBeDefined();
    expect(screen.getByTestId("phase-2-6-banner")).toBeDefined();
    await waitFor(() => {
      expect(screen.getByTestId("account-selector")).toBeDefined();
    });
  });

  it("shows default mode OFF after settings load", async () => {
    render(<AutoTradePage />);
    await waitFor(() => {
      expect(screen.getByTestId("current-mode").textContent).toBe("OFF");
    });
  });

  it("toggles to PAPER_ONLY on the Paper button", async () => {
    render(<AutoTradePage />);
    await waitFor(() => screen.getByTestId("btn-paper"));
    fireEvent.click(screen.getByTestId("btn-paper"));
    await waitFor(() => {
      expect(screen.getByTestId("current-mode").textContent).toBe("Paper only");
    });
  });

  it("opens the risk-acknowledgement modal on Live auto request success", async () => {
    render(<AutoTradePage />);
    await waitFor(() => screen.getByTestId("btn-live-auto"));
    fireEvent.click(screen.getByTestId("btn-live-auto"));
    await waitFor(() => screen.getByTestId("risk-ack-confirm"));
    const confirm = screen.getByTestId("risk-ack-confirm") as HTMLButtonElement;
    expect(confirm.disabled).toBe(true);
    // Tick the box → confirm becomes enabled.
    fireEvent.click(screen.getByTestId("risk-ack-checkbox"));
    expect(confirm.disabled).toBe(false);
  });

  it("renders rejection list when Live auto request is rejected", async () => {
    mockState.liveValid = false;
    render(<AutoTradePage />);
    await waitFor(() => screen.getByTestId("btn-live-auto"));
    fireEvent.click(screen.getByTestId("btn-live-auto"));
    await waitFor(() => screen.getByTestId("rejection-list"));
    expect(screen.getByTestId("rejection-list").textContent).toContain("MAX_CAPITAL_VND_REQUIRED");
  });

  it("confirms Live auto when the box is checked and the API returns VALID", async () => {
    render(<AutoTradePage />);
    await waitFor(() => screen.getByTestId("btn-live-auto"));
    fireEvent.click(screen.getByTestId("btn-live-auto"));
    await waitFor(() => screen.getByTestId("risk-ack-checkbox"));
    fireEvent.click(screen.getByTestId("risk-ack-checkbox"));
    fireEvent.click(screen.getByTestId("risk-ack-confirm"));
    await waitFor(() => {
      expect(screen.getByTestId("current-mode").textContent).toBe("Live auto");
    });
  });

  it("renders the emergency stop button only when mode is not OFF", async () => {
    render(<AutoTradePage />);
    await waitFor(() => screen.getByTestId("btn-paper"));
    // Mode is OFF → no emergency-stop button yet.
    expect(screen.queryByTestId("btn-emergency-stop")).toBeNull();
    // Enable paper → button appears.
    fireEvent.click(screen.getByTestId("btn-paper"));
    await waitFor(() => screen.getByTestId("btn-emergency-stop"));
  });

  it("performs emergency stop and returns mode to OFF", async () => {
    render(<AutoTradePage />);
    await waitFor(() => screen.getByTestId("btn-paper"));
    fireEvent.click(screen.getByTestId("btn-paper"));
    await waitFor(() => screen.getByTestId("btn-emergency-stop"));
    fireEvent.click(screen.getByTestId("btn-emergency-stop"));
    await waitFor(() => screen.getByTestId("stop-confirm"));
    fireEvent.click(screen.getByTestId("stop-confirm"));
    await waitFor(() => {
      expect(screen.getByTestId("current-mode").textContent).toBe("OFF");
    });
  });

  it("renders the audit log table with at least one row", async () => {
    render(<AutoTradePage />);
    await waitFor(() => screen.getByTestId("audit-log-table"));
    expect(screen.getByTestId("audit-log-table").textContent).toContain("AUTO_TRADE_ENABLE_PAPER");
  });

  it("never renders a 'submit live order' affordance", async () => {
    render(<AutoTradePage />);
    await waitFor(() => screen.getByTestId("auto-trade-page"));
    expect(screen.queryByText(/submit.*order/i)).toBeNull();
  });

  // ── CRITICAL invariant: re-auth modal must NEVER leak the password to
  // the backend. The password goes only to Supabase via the JS SDK.
  it("never sends the password to the backend during re-auth", async () => {
    mockState.rejectManualConfirmWithReauth = true;
    render(<AutoTradePage />);
    await waitFor(() => screen.getByTestId("btn-manual-confirm"));
    fireEvent.click(screen.getByTestId("btn-manual-confirm"));
    await waitFor(() => screen.getByTestId("reauth-password"));

    const SENTINEL = "PASSWORD_THAT_MUST_NOT_LEAK";
    fireEvent.change(screen.getByTestId("reauth-email"), {
      target: { value: "user@example.com" },
    });
    fireEvent.change(screen.getByTestId("reauth-password"), {
      target: { value: SENTINEL },
    });
    apiCalls.length = 0;
    fireEvent.click(screen.getByTestId("reauth-submit"));
    // Give the click a tick to resolve.
    await new Promise((r) => setTimeout(r, 50));

    // NO backend api call may contain the sentinel password in its body
    // or URL. Password flows only to Supabase via the JS SDK (mocked).
    for (const c of apiCalls) {
      const body = typeof c.init?.body === "string" ? c.init.body : "";
      expect(body).not.toContain(SENTINEL);
      expect(c.path).not.toContain(SENTINEL);
    }
  });

  it("includes the stop reason in the emergency-stop API call", async () => {
    render(<AutoTradePage />);
    await waitFor(() => screen.getByTestId("btn-paper"));
    fireEvent.click(screen.getByTestId("btn-paper"));
    await waitFor(() => screen.getByTestId("btn-emergency-stop"));
    fireEvent.click(screen.getByTestId("btn-emergency-stop"));
    await waitFor(() => screen.getByTestId("stop-confirm"));
    apiCalls.length = 0;
    fireEvent.click(screen.getByTestId("stop-confirm"));
    await waitFor(() => {
      expect(apiCalls.some((c) => c.path === "/auto-trade/emergency-stop")).toBe(true);
    });
    const stopCall = apiCalls.find((c) => c.path === "/auto-trade/emergency-stop");
    const body = JSON.parse(stopCall!.init!.body as string);
    expect(body.reason).toBeDefined();
    expect(body.account_id).toBe("acc-1");
  });

  // ── Phase 2.9 engine section ───────────────────────────────────────────

  it("renders the Phase 2.9 engine warning + engine controls", async () => {
    render(<AutoTradePage />);
    await waitFor(() => screen.getByTestId("phase-2-9-engine-warning"));
    expect(screen.getByTestId("engine-run-status").textContent).toContain("NO RUN");
    // Start button enabled (no active run); Pause/Stop disabled.
    const start = screen.getByTestId("engine-start") as HTMLButtonElement;
    const pause = screen.getByTestId("engine-pause") as HTMLButtonElement;
    const stop = screen.getByTestId("engine-stop") as HTMLButtonElement;
    expect(start.disabled).toBe(false);
    expect(pause.disabled).toBe(true);
    expect(stop.disabled).toBe(true);
  });

  it("calls POST /auto-trade/runs/start with the selected account", async () => {
    render(<AutoTradePage />);
    await waitFor(() => screen.getByTestId("engine-start"));
    apiCalls.length = 0;
    fireEvent.click(screen.getByTestId("engine-start"));
    await waitFor(() =>
      expect(
        apiCalls.some((c) => c.path === "/auto-trade/runs/start" && c.init?.method === "POST"),
      ).toBe(true),
    );
    const call = apiCalls.find(
      (c) => c.path === "/auto-trade/runs/start" && c.init?.method === "POST",
    );
    const body = JSON.parse(call!.init!.body as string);
    expect(body.account_id).toBe("acc-1");
    expect(body.strategy_id).toBe("default");
  });
});
