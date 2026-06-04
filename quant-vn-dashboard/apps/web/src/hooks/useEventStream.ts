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
 * status badge and fall back to REST polling.
 *
 * Stability: ``onMessage`` and ``eventTypes`` are held in refs and the effect
 * depends only on ``path``, ``enabled``, and a VALUE-based join of the event
 * names. This is deliberate — callers commonly pass an inline ``eventTypes``
 * array literal whose identity changes every render. Depending on the array
 * reference would tear down and recreate the EventSource on every parent
 * re-render (e.g. each incoming quote), flipping ``connected`` false→true
 * repeatedly and making the UI flicker. With this design the connection is
 * created once per ``path`` and survives unrelated re-renders.
 */
export function useEventStream<T = unknown>({
  path,
  eventTypes,
  onMessage,
  enabled = true,
}: Options<T>): StreamState {
  const [connected, setConnected] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Latest callback + event list, read inside the listener without becoming
  // effect dependencies (so they never trigger a reconnect).
  const onMessageRef = useRef(onMessage);
  onMessageRef.current = onMessage;
  const eventTypesRef = useRef(eventTypes);
  eventTypesRef.current = eventTypes;

  // Value-based dependency so re-renders with a fresh array literal of the
  // SAME names do not recreate the connection.
  const eventTypesKey = eventTypes.join(",");

  useEffect(() => {
    if (!enabled || !path) return;
    let cancelled = false;

    const source = new EventSource(path);

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

    eventTypesRef.current.forEach((eventType) => {
      source.addEventListener(eventType, (e: MessageEvent) => {
        if (cancelled) return;
        try {
          const parsed = JSON.parse(e.data) as T;
          onMessageRef.current(eventType, parsed);
        } catch {
          setError("Malformed event payload");
        }
      });
    });

    return () => {
      cancelled = true;
      source.close();
      setConnected(false);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [path, enabled, eventTypesKey]);

  return { connected, error };
}
