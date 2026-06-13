import { act, renderHook, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { useAsyncResource } from "./useAsyncResource";

const FALLBACK = { kind: "mock" } as const;

describe("useAsyncResource", () => {
  it("returns live data on success and isMock=false", async () => {
    const fetcher = vi.fn().mockResolvedValue({ kind: "live" });
    const { result } = renderHook(() => useAsyncResource({ fetcher, mockFallback: FALLBACK }));
    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.data).toEqual({ kind: "live" });
    expect(result.current.isMock).toBe(false);
    expect(result.current.error).toBeNull();
  });

  it("on error with disableMockOnError=true: keeps fallback as data, sets isMock+error", async () => {
    const fetcher = vi.fn().mockRejectedValue(new Error("network down"));
    const { result } = renderHook(() =>
      useAsyncResource({
        fetcher,
        mockFallback: FALLBACK,
        disableMockOnError: true,
      }),
    );
    await waitFor(() => expect(result.current.isLoading).toBe(false));
    // data stays at the initial mockFallback because that's the
    // useState initial value, but isMock=true + error is set so
    // the caller can render an error banner instead of silently
    // displaying fake content.
    expect(result.current.isMock).toBe(true);
    expect(result.current.error).toBe("network down");
  });

  it("on error with disableMockOnError=false: substitutes mockFallback (legacy mock-backed hooks)", async () => {
    const fetcher = vi.fn().mockRejectedValue(new Error("boom"));
    const { result } = renderHook(() =>
      useAsyncResource({
        fetcher,
        mockFallback: FALLBACK,
        disableMockOnError: false,
      }),
    );
    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.data).toEqual(FALLBACK);
    expect(result.current.isMock).toBe(true);
    expect(result.current.error).toBe("boom");
  });

  it("first-load error is never 'stale' (no real data shown yet)", async () => {
    const fetcher = vi.fn().mockRejectedValue(new Error("down"));
    const { result } = renderHook(() =>
      useAsyncResource({ fetcher, mockFallback: FALLBACK, disableMockOnError: true }),
    );
    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.hasLoadedReal).toBe(false);
    expect(result.current.stale).toBe(false); // never loaded real → not stale
    expect(result.current.lastUpdatedAt).toBeNull();
  });

  it("keeps last good data + flags stale when a later refetch fails", async () => {
    const fetcher = vi
      .fn()
      .mockResolvedValueOnce({ kind: "live" })
      .mockRejectedValueOnce(new Error("down"));
    const { result } = renderHook(() =>
      useAsyncResource({ fetcher, mockFallback: FALLBACK, disableMockOnError: true }),
    );
    await waitFor(() => expect(result.current.hasLoadedReal).toBe(true));
    expect(result.current.lastUpdatedAt).not.toBeNull();

    act(() => result.current.refetch());
    await waitFor(() => expect(result.current.error).toBe("down"));
    expect(result.current.data).toEqual({ kind: "live" }); // last good kept
    expect(result.current.stale).toBe(true);
  });
});
