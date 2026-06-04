import { describe, expect, it, beforeEach, vi } from "vitest";
import { act, renderHook } from "@testing-library/react";
import { useEventStream } from "./useEventStream";

class FakeEventSource {
  static instances: FakeEventSource[] = [];
  url: string;
  onopen: (() => void) | null = null;
  onerror: (() => void) | null = null;
  listeners: Record<string, ((e: { data: string }) => void)[]> = {};
  closed = false;
  constructor(url: string) {
    this.url = url;
    FakeEventSource.instances.push(this);
  }
  addEventListener(type: string, cb: (e: { data: string }) => void) {
    (this.listeners[type] ??= []).push(cb);
  }
  close() {
    this.closed = true;
  }
  emit(type: string, data: unknown) {
    (this.listeners[type] ?? []).forEach((cb) => cb({ data: JSON.stringify(data) }));
  }
}

beforeEach(() => {
  FakeEventSource.instances = [];
  // @ts-expect-error — inject a fake EventSource into the jsdom global.
  globalThis.EventSource = FakeEventSource;
});

describe("useEventStream stability", () => {
  it("creates the EventSource ONCE and does not recreate it on re-render with a fresh eventTypes array literal", () => {
    const { rerender } = renderHook(
      ({ n }) =>
        // `eventTypes` is a new array identity every render — the regression
        // that caused the live-quotes flicker. It must NOT recreate the stream.
        useEventStream({ path: "/x", eventTypes: ["a"], onMessage: () => void n }),
      { initialProps: { n: 0 } },
    );
    rerender({ n: 1 });
    rerender({ n: 2 });
    expect(FakeEventSource.instances.length).toBe(1);
    expect(FakeEventSource.instances[0].closed).toBe(false);
  });

  it("recreates the EventSource when the path changes", () => {
    const { rerender } = renderHook(
      ({ path }) => useEventStream({ path, eventTypes: ["a"], onMessage: () => {} }),
      { initialProps: { path: "/a" } },
    );
    rerender({ path: "/b" });
    expect(FakeEventSource.instances.length).toBe(2);
    expect(FakeEventSource.instances[0].closed).toBe(true);
  });

  it("reflects connected on open and disconnected on error, and routes messages to the latest onMessage", () => {
    const onMessage = vi.fn();
    const { result, rerender } = renderHook(
      ({ cb }) => useEventStream<{ v: number }>({ path: "/x", eventTypes: ["tick"], onMessage: cb }),
      { initialProps: { cb: onMessage } },
    );
    const es = FakeEventSource.instances[0];

    act(() => es.onopen?.());
    expect(result.current.connected).toBe(true);

    // Swap the callback; the stream must not be recreated but should call the latest.
    const onMessage2 = vi.fn();
    rerender({ cb: onMessage2 });
    expect(FakeEventSource.instances.length).toBe(1);
    act(() => es.emit("tick", { v: 7 }));
    expect(onMessage2).toHaveBeenCalledWith("tick", { v: 7 });
    expect(onMessage).not.toHaveBeenCalled();

    act(() => es.onerror?.());
    expect(result.current.connected).toBe(false);
  });
});
