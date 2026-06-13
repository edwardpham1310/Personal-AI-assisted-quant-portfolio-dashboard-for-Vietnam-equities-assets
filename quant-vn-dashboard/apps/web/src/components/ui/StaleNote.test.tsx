import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";

import { StaleNote } from "./StaleNote";

describe("StaleNote", () => {
  it("renders nothing when there is no timestamp and not stale", () => {
    const { container } = render(<StaleNote asOf={null} stale={false} />);
    expect(container.firstChild).toBeNull();
  });

  it("shows an 'As of' note for fresh data", () => {
    render(<StaleNote asOf="2026-01-02" stale={false} />);
    expect(screen.getByText(/As of · 2026-01-02/)).toBeDefined();
  });

  it("shows a 'Latest synced' stale note (keep-last-good)", () => {
    render(<StaleNote asOf="2026-01-02" stale />);
    const note = screen.getByText(/Latest synced/);
    expect(note).toBeDefined();
    expect(note.textContent).toMatch(/showing last synced data/i);
  });
});
