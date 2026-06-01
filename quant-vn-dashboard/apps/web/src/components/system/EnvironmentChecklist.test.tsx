import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { EnvironmentChecklist } from "./EnvironmentChecklist";

describe("EnvironmentChecklist", () => {
  it("renders an OK pill when no secrets are missing", () => {
    render(<EnvironmentChecklist missingSecrets={[]} />);
    expect(screen.getByText("OK")).toBeDefined();
    expect(screen.getByText(/All required secrets are present/i)).toBeDefined();
  });

  it("renders the friendly name for each missing secret", () => {
    render(<EnvironmentChecklist missingSecrets={["supabase_url", "ssi_consumer_id"]} />);
    expect(screen.getByText("2 missing")).toBeDefined();
    expect(screen.getByText(/Supabase URL/)).toBeDefined();
    expect(screen.getByText(/SSI consumer ID/)).toBeDefined();
    // The raw key is shown in uppercase code form.
    expect(screen.getByText("SUPABASE_URL")).toBeDefined();
  });

  it("falls back to the raw key for unknown secrets", () => {
    render(<EnvironmentChecklist missingSecrets={["mystery_value"]} />);
    expect(screen.getByText("MYSTERY_VALUE")).toBeDefined();
  });
});
