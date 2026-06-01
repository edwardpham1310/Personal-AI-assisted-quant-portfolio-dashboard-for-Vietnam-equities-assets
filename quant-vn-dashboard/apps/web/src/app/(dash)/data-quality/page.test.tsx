import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import type { DataQualitySnapshot, SystemStatus } from "@/hooks/useSystemStatus";

const apiMock = vi.fn();

vi.mock("@/lib/api", () => ({
  useApi: () => apiMock,
  ApiError: class ApiError extends Error {},
}));

const statusRefresh = vi.fn();
const dqRefresh = vi.fn();
let mockStatus: SystemStatus | null = null;
let mockDq: DataQualitySnapshot | null = null;
let mockStatusLoading = false;
let mockDqLoading = false;
let mockStatusError: string | null = null;
let mockDqError: string | null = null;

vi.mock("@/hooks/useSystemStatus", async () => {
  const actual =
    await vi.importActual<typeof import("@/hooks/useSystemStatus")>("@/hooks/useSystemStatus");
  return {
    ...actual,
    useSystemStatus: () => ({
      data: mockStatus,
      loading: mockStatusLoading,
      error: mockStatusError,
      refresh: statusRefresh,
    }),
  };
});

vi.mock("@/hooks/useDataQuality", () => ({
  useDataQuality: () => ({
    data: mockDq,
    loading: mockDqLoading,
    error: mockDqError,
    refresh: dqRefresh,
  }),
}));

import DataQualityPage from "./page";

const STATUS_OK: SystemStatus = {
  app_env: "development",
  missing_secrets: [],
  ssi_base_url: "https://fc-data.ssi.com.vn",
  redis_configured: false,
  provider: {
    name: "mock",
    ready: true,
    mock: true,
    token_cached: true,
    last_call_ts: "2026-05-29T10:00:00Z",
    note: null,
    error: null,
  },
  cache: {
    name: "memory",
    configured: false,
    healthy: true,
    last_poll_ts: null,
    last_poll_ok: null,
    last_poll_error: null,
    error: null,
  },
  supabase: { configured: true, url_host: "localhost" },
  duckdb: {
    configured: true,
    path: "./data/duckdb/quant_vn.duckdb",
    exists: false,
    size_bytes: null,
  },
  poller: { enabled: false, running: false, active_symbols_count: 0 },
  data_quality: {
    timestamp: "2026-05-29T10:00:00Z",
    stale_quote_count: 0,
    total_tracked_symbols: 6,
    symbols_without_quote: [],
    stale_quote_rows: [],
    cache_misses: 0,
    provider_errors: 0,
    last_successful_sync: null,
    notes: [],
  },
  checked_at: "2026-05-29T10:00:00Z",
};

const DQ_EMPTY: DataQualitySnapshot = {
  timestamp: "2026-05-29T10:00:00Z",
  stale_quote_count: 0,
  total_tracked_symbols: 6,
  symbols_without_quote: [],
  stale_quote_rows: [],
  cache_misses: 0,
  provider_errors: 0,
  last_successful_sync: null,
  notes: [],
};

beforeEach(() => {
  apiMock.mockReset();
  statusRefresh.mockReset();
  dqRefresh.mockReset();
  mockStatus = null;
  mockDq = null;
  mockStatusLoading = false;
  mockDqLoading = false;
  mockStatusError = null;
  mockDqError = null;
});

describe("DataQualityPage", () => {
  it("renders the research-dashboard disclaimer", () => {
    mockStatus = STATUS_OK;
    mockDq = DQ_EMPTY;
    render(<DataQualityPage />);
    // The phrase appears in the header subtitle and the disclaimer banner.
    expect(screen.getAllByText(/Research dashboard/i).length).toBeGreaterThan(0);
  });

  it("renders empty state when zero stale quotes", () => {
    mockStatus = STATUS_OK;
    mockDq = DQ_EMPTY;
    render(<DataQualityPage />);
    expect(screen.getByText(/No stale quotes/i)).toBeDefined();
    expect(screen.getByText(/Every tracked symbol has a cached quote/i)).toBeDefined();
  });

  it("renders the provider, cache, and poller cards", () => {
    mockStatus = STATUS_OK;
    mockDq = DQ_EMPTY;
    render(<DataQualityPage />);
    expect(screen.getByText("Market data provider")).toBeDefined();
    expect(screen.getByText("Hot cache")).toBeDefined();
    expect(screen.getByText("Market poller")).toBeDefined();
  });

  it("shows missing symbols when the API reports them", () => {
    mockStatus = STATUS_OK;
    mockDq = { ...DQ_EMPTY, symbols_without_quote: ["FPT", "MWG"] };
    render(<DataQualityPage />);
    expect(screen.getByText("FPT")).toBeDefined();
    expect(screen.getByText("MWG")).toBeDefined();
  });
});
