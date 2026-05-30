import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { ProviderCard } from "./ProviderCard";

describe("ProviderCard", () => {
  it("renders the provider name and an OK status pill", () => {
    render(
      <ProviderCard
        provider={{
          name: "mock",
          ready: true,
          mock: true,
          token_cached: true,
          last_call_ts: "2026-05-29T10:00:00Z",
          note: null,
          error: null,
        }}
      />,
    );

    expect(screen.getByText("Market data provider")).toBeDefined();
    expect(screen.getByText("OK")).toBeDefined();
    expect(screen.getByText("mock")).toBeDefined();
  });

  it("shows an ERROR pill and renders the redacted error string", () => {
    render(
      <ProviderCard
        provider={{
          name: "ssi",
          ready: false,
          mock: false,
          token_cached: false,
          last_call_ts: null,
          note: "status_unavailable",
          error: "ConnectionError",
        }}
      />,
    );
    expect(screen.getByText("ERROR")).toBeDefined();
    expect(screen.getByText("ConnectionError")).toBeDefined();
  });
});
