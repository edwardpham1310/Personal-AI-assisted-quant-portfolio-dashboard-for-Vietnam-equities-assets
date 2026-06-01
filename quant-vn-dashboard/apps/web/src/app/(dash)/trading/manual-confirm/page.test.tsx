import { describe, expect, it, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import ManualConfirmPage from "./page";

const apiCalls: Array<{ path: string; init?: RequestInit }> = [];

type IntentStatus =
  | "DRAFT"
  | "PREVIEWED"
  | "CONFIRM_REQUIRED"
  | "CONFIRMED"
  | "SUBMITTED";

const mockState: { status: IntentStatus; gateOpen: boolean; dryRun: boolean } = {
  status: "DRAFT",
  gateOpen: false,
  dryRun: true,
};

const baseIntent = () => ({
  id: "intent-1",
  user_id: "u1",
  account_id: "acc-1",
  source_type: "MANUAL",
  source_id: null,
  symbol: "FPT",
  side: "BUY",
  order_type: "LIMIT",
  quantity: 100,
  limit_price: 86000,
  preview_id: null,
  status: mockState.status,
  validation_snapshot: null,
  warnings: [],
  rejection_reasons: [],
  created_at: "2026-05-31T00:00:00Z",
  confirmed_at: null,
  submitted_at: null,
  updated_at: null,
});

const baseGate = () => ({
  live_order_enabled: mockState.gateOpen,
  manual_confirm_enabled: mockState.gateOpen,
  read_only_disabled: mockState.gateOpen,
  not_using_mock: mockState.gateOpen,
  dry_run_disabled: mockState.gateOpen,
  all_open: mockState.gateOpen,
});

const stableApiFn = async (path: string, init?: RequestInit) => {
  apiCalls.push({ path, init });
  if (path === "/trading") {
    return [
      {
        id: "acc-1",
        user_id: "u1",
        broker: "SSI",
        account_number_masked: "****5678",
        account_alias: "Main",
        read_only_enabled: true,
        trading_enabled: false,
        created_at: null,
        updated_at: null,
      },
    ];
  }
  if (path.startsWith("/trading/live-order-intents") && (!init || init.method !== "POST")) {
    return [];
  }
  if (path.startsWith("/auto-trade/reauth")) {
    return { ok: true, last_reauth_at: "2026-05-31T00:00:00Z", valid_for_seconds: 300 };
  }
  if (path === "/trading/live-order-intents" && init?.method === "POST") {
    mockState.status = "DRAFT";
    return baseIntent();
  }
  if (path.endsWith("/preview")) {
    mockState.status = "PREVIEWED";
    return {
      intent: baseIntent(),
      validation_status: "VALID",
      rejection_reasons: [],
      warnings: [],
      is_live_submission_performed: false,
      is_dry_run: mockState.dryRun,
      submission: null,
      gate_status: baseGate(),
    };
  }
  if (path.endsWith("/request-confirmation")) {
    mockState.status = "CONFIRM_REQUIRED";
    return {
      intent: baseIntent(),
      validation_status: "VALID",
      rejection_reasons: [],
      warnings: [],
      is_live_submission_performed: false,
      is_dry_run: mockState.dryRun,
      submission: null,
      gate_status: baseGate(),
    };
  }
  if (path.endsWith("/confirm")) {
    const body = JSON.parse(init?.body as string);
    if (!body.risk_acknowledged) {
      return {
        intent: baseIntent(),
        validation_status: "REJECTED",
        rejection_reasons: ["RISK_ACK_REQUIRED"],
        warnings: [],
        is_live_submission_performed: false,
        is_dry_run: mockState.dryRun,
        submission: null,
        gate_status: baseGate(),
      };
    }
    mockState.status = "CONFIRMED";
    return {
      intent: baseIntent(),
      validation_status: "VALID",
      rejection_reasons: [],
      warnings: [],
      is_live_submission_performed: false,
      is_dry_run: mockState.dryRun,
      submission: null,
      gate_status: baseGate(),
    };
  }
  if (path.endsWith("/submit")) {
    mockState.status = "SUBMITTED";
    return {
      intent: baseIntent(),
      validation_status: "VALID",
      rejection_reasons: [],
      warnings: [],
      is_live_submission_performed: mockState.gateOpen && !mockState.dryRun,
      is_dry_run: mockState.dryRun,
      submission: { status: "DRY_RUN_OK" },
      gate_status: baseGate(),
    };
  }
  if (path.endsWith("/cancel")) {
    mockState.status = "DRAFT";
    return {
      intent: baseIntent(),
      validation_status: "VALID",
      rejection_reasons: [],
      warnings: [],
      is_live_submission_performed: false,
      is_dry_run: mockState.dryRun,
      submission: null,
      gate_status: baseGate(),
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
  mockState.status = "DRAFT";
  mockState.gateOpen = false;
  mockState.dryRun = true;
});

describe("ManualConfirmPage", () => {
  it("renders + shows DRY RUN banner by default", async () => {
    render(<ManualConfirmPage />);
    expect(screen.getByTestId("manual-confirm-page")).toBeDefined();
    await waitFor(() => screen.getByTestId("account-selector"));
    expect(screen.getByTestId("dry-run-banner")).toBeDefined();
    expect(screen.queryByTestId("live-warning-banner")).toBeNull();
  });

  it("creates an intent and reveals step-2 preview button", async () => {
    render(<ManualConfirmPage />);
    await waitFor(() => screen.getByTestId("loi-create"));
    fireEvent.submit(screen.getByTestId("create-intent-form"));
    await waitFor(() => screen.getByTestId("step-preview"));
    expect(
      (screen.getByTestId("step-preview") as HTMLButtonElement).disabled,
    ).toBe(false);
  });

  it("step-submit is disabled until status === CONFIRMED", async () => {
    render(<ManualConfirmPage />);
    await waitFor(() => screen.getByTestId("loi-create"));
    fireEvent.submit(screen.getByTestId("create-intent-form"));
    await waitFor(() => screen.getByTestId("step-submit-open"));
    const btn = screen.getByTestId("step-submit-open") as HTMLButtonElement;
    expect(btn.disabled).toBe(true);
  });

  it("walks the full DRY-RUN flow: create → preview → request-confirmation → reauth → risk-ack → submit", async () => {
    render(<ManualConfirmPage />);
    await waitFor(() => screen.getByTestId("loi-create"));
    fireEvent.submit(screen.getByTestId("create-intent-form"));
    await waitFor(() => screen.getByTestId("step-preview"));
    fireEvent.click(screen.getByTestId("step-preview"));
    await waitFor(() =>
      expect(screen.getByTestId("active-intent-status").textContent).toBe(
        "PREVIEWED",
      ),
    );
    fireEvent.click(screen.getByTestId("step-request-confirmation"));
    await waitFor(() => screen.getByTestId("reauth-submit"));
    // Re-auth modal opens — typing password.
    fireEvent.change(screen.getByTestId("reauth-email"), {
      target: { value: "u@example.com" },
    });
    fireEvent.change(screen.getByTestId("reauth-password"), {
      target: { value: "PWNEVERLEAK" },
    });
    apiCalls.length = 0;
    fireEvent.click(screen.getByTestId("reauth-submit"));
    await waitFor(() => screen.getByTestId("risk-ack-confirm"));
    // Risk-ack modal — confirm disabled until checked.
    const ackBtn = screen.getByTestId("risk-ack-confirm") as HTMLButtonElement;
    expect(ackBtn.disabled).toBe(true);
    fireEvent.click(screen.getByTestId("risk-ack-checkbox"));
    expect(ackBtn.disabled).toBe(false);
    fireEvent.click(ackBtn);
    await waitFor(() => screen.getByTestId("final-submit"));
    // Dry-run label visible.
    expect(screen.getByTestId("modal-dry-run-label")).toBeDefined();
    fireEvent.click(screen.getByTestId("final-submit"));
    await waitFor(() => {
      expect(screen.getByTestId("active-intent-status").textContent).toBe(
        "SUBMITTED",
      );
    });
  });

  it("password never reaches the backend", async () => {
    render(<ManualConfirmPage />);
    await waitFor(() => screen.getByTestId("loi-create"));
    fireEvent.submit(screen.getByTestId("create-intent-form"));
    await waitFor(() => screen.getByTestId("step-preview"));
    fireEvent.click(screen.getByTestId("step-preview"));
    await waitFor(() =>
      expect(screen.getByTestId("active-intent-status").textContent).toBe(
        "PREVIEWED",
      ),
    );
    fireEvent.click(screen.getByTestId("step-request-confirmation"));
    await waitFor(() => screen.getByTestId("reauth-submit"));
    const SENTINEL = "PASSWORD_THAT_MUST_NOT_LEAK";
    fireEvent.change(screen.getByTestId("reauth-email"), {
      target: { value: "u@example.com" },
    });
    fireEvent.change(screen.getByTestId("reauth-password"), {
      target: { value: SENTINEL },
    });
    apiCalls.length = 0;
    fireEvent.click(screen.getByTestId("reauth-submit"));
    await new Promise((r) => setTimeout(r, 50));
    for (const c of apiCalls) {
      const body = typeof c.init?.body === "string" ? c.init.body : "";
      expect(body).not.toContain(SENTINEL);
      expect(c.path).not.toContain(SENTINEL);
    }
  });
});
