"use client";

import { useEffect, useRef, useState } from "react";

type Options<T> = {
  /** URL on the Next.js BFF (e.g. ``/api/stream/quotes?symbols=…``). */
  path: string;
  /** SSE event names to listen for. */
  eventTypes: string[];
  /** Called when any of the listed events arrive. */
  onMessage: (eventType: string, data: T) => void;
  /** When false, the hook does not open a connection. */
  enabled?: boolean;
};

export type StreamState = {
  connected: boolean;
  error: string | null;
};

/**
 * Thin EventSource wrapper. Browser EventSources reconnect automatically on
 * transport-level disconnects, so we don't need to implement exponential
 * backoff ourselves — we only expose ``connected`` so callers can show a
 * "Reconnecting…" badge and fall back to REST polling.
 */
export function useEventStream<T = unknown>({
  path,
  eventTypes,
  onMessage,
  enabled = true,
}: Options<T>): StreamState {
  const [connected, setConnected] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const sourceRef = useRef<EventSource | null>(null);

  useEffect(() => {
    if (!enabled) return;
    let cancelled = false;

    const source = new EventSource(path);
    sourceRef.current = source;

    source.onopen = () => {
      if (cancelled) return;
      setConnected(true);
      setError(null);
    };

    source.onerror = () => {
      if (cancelled) return;
      setConnected(false);
      setError("Stream disconnected");
    };

    eventTypes.forEach((eventType) => {
      source.addEventListener(eventType, (e: MessageEvent) => {
        if (cancelled) return;
        try {
          const parsed = JSON.parse(e.data) as T;
          onMessage(eventType, parsed);
        } catch {
          setError("Malformed event payload");
        }
      });
    });

    return () => {
      cancelled = true;
      source.close();
      sourceRef.current = null;
      setConnected(false);
    };
  }, [path, enabled, eventTypes, onMessage]);

  return { connected, error };
}
