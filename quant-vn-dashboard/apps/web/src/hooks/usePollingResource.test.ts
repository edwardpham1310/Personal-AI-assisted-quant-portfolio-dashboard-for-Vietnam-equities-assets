import { act, renderHook, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { usePollingResource } from "./usePollingResource";

describe("usePollingResource — keep last good data", () => {
  it("retains the last good data on a refetch error and flags stale", async () => {
    const fetcher = vi
      .fn()
      .mockResolvedValueOnce([1, 2, 3])
      .mockRejectedValueOnce(new Error("network down"));

    const { result } = renderHook(() =>
      usePollingResource<number[]>({ fetcher, intervalMs: null }),
    );

    // First load succeeds.
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.data).toEqual([1, 2, 3]);
    expect(result.current.stale).toBe(false);
    expect(result.current.lastUpdatedAt).not.toBeNull();

    // Refetch fails — data stays, error surfaces, stale flips true.
    await act(async () => {
      await result.current.refresh();
    });
    expect(result.current.error).toBe("network down");
    expect(result.current.data).toEqual([1, 2, 3]); // last good kept (no flicker)
    expect(result.current.stale).toBe(true);
  });

  it("clears the error on a successful refetch", async () => {
    const fetcher = vi
      .fn()
      .mockRejectedValueOnce(new Error("boom"))
      .mockResolvedValueOnce([9]);
    const { result } = renderHook(() =>
      usePollingResource<number[]>({ fetcher, intervalMs: null }),
    );
    await waitFor(() => expect(result.current.error).toBe("boom"));
    await act(async () => {
      await result.current.refresh();
    });
    expect(result.current.error).toBeNull();
    expect(result.current.data).toEqual([9]);
    expect(result.current.stale).toBe(false);
  });
});
