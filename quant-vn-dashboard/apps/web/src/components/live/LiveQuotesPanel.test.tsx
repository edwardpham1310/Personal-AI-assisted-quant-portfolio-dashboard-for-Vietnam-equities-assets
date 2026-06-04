import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import type { LiveQuote, TransportStatus } from "@/hooks/useLiveQuotes";

const useLiveQuotesMock = vi.fn();
vi.mock("@/hooks/useLiveQuotes", () => ({
  useLiveQuotes: (symbols: string[]) => useLiveQuotesMock(symbols),
}));

import { LiveQuotesPanel } from "./LiveQuotesPanel";

function setHook(opts: {
  quotes?: LiveQuote[];
  lastUpdate?: string | null;
  transportStatus: TransportStatus;
  hasEverReceivedData?: boolean;
  error?: string | null;
}) {
  useLiveQuotesMock.mockReturnValue({
    quotes: opts.quotes ?? [],
    lastUpdate: opts.lastUpdate ?? null,
    transportStatus: opts.transportStatus,
    hasEverReceivedData: opts.hasEverReceivedData ?? (opts.quotes?.length ?? 0) > 0,
    error: opts.error ?? null,
  });
}

const quote = (over: Partial<LiveQuote> = {}): LiveQuote => ({
  symbol: "FPT",
  price: 60_000,
  change: 100,
  ts: "2026-06-04T03:00:00Z",
  stale: false,
  source: "ssi",
  ...over,
});

beforeEach(() => useLiveQuotesMock.mockReset());

describe("LiveQuotesPanel", () => {
  it("no quotes ever received → calm cold-cache state, no alarming badge", () => {
    setHook({ transportStatus: "connecting", hasEverReceivedData: false });
    render(<LiveQuotesPanel symbols={["FPT"]} />);
    expect(screen.getByText(/Cache is cold/i)).toBeDefined();
    // "connecting" shows no badge — nothing scary on startup.
    expect(screen.queryByText("Offline")).toBeNull();
    expect(screen.queryByText("Disconnected")).toBeNull();
  });

  it("REST fallback success → calm 'Polling' badge (not a failure) with the table", () => {
    setHook({ transportStatus: "polling", quotes: [quote()], lastUpdate: quote().ts });
    render(<LiveQuotesPanel symbols={["FPT"]} />);
    expect(screen.getByText("Polling")).toBeDefined();
    expect(screen.getByText("FPT")).toBeDefined();
    expect(screen.queryByText("Offline")).toBeNull();
  });

  it("SSE dropped but data retained → 'Reconnecting', quotes still shown", () => {
    setHook({ transportStatus: "reconnecting", quotes: [quote()], lastUpdate: quote().ts });
    render(<LiveQuotesPanel symbols={["FPT"]} />);
    expect(screen.getByText("Reconnecting")).toBeDefined();
    expect(screen.getByText("FPT")).toBeDefined();
  });

  it("live with fresh data → 'Live' badge and rows", () => {
    setHook({ transportStatus: "live", quotes: [quote({ symbol: "MWG" })] });
    render(<LiveQuotesPanel symbols={["MWG"]} />);
    expect(screen.getByText("Live")).toBeDefined();
    expect(screen.getByText("MWG")).toBeDefined();
  });

  it("offline (poll failing) → honest 'Offline' badge + error message", () => {
    setHook({ transportStatus: "offline", error: "Polling failed", hasEverReceivedData: false });
    render(<LiveQuotesPanel symbols={["FPT"]} />);
    expect(screen.getByText("Offline")).toBeDefined();
    expect(screen.getByText("Polling failed")).toBeDefined();
  });

  it("Stale is timestamp-driven and shown alongside any status (stable, not connection-coupled)", () => {
    setHook({ transportStatus: "live", quotes: [quote({ stale: true })] });
    render(<LiveQuotesPanel symbols={["FPT"]} />);
    expect(screen.getByText("Live")).toBeDefined();
    expect(screen.getByText("Stale")).toBeDefined();
  });

  it("never renders 'Invalid Date' when a quote ts is missing", () => {
    const bad = { ...quote(), ts: undefined } as unknown as LiveQuote;
    setHook({ transportStatus: "polling", quotes: [bad] });
    const { container } = render(<LiveQuotesPanel symbols={["FPT"]} />);
    expect(container.textContent).not.toContain("Invalid Date");
  });
});
