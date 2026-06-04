"use client";

import { Card } from "@/components/ui/Card";
import { useLiveQuotes, type TransportStatus } from "@/hooks/useLiveQuotes";
import { formatNumber } from "@/lib/format";

/** Format a quote timestamp safely — missing/invalid `ts` renders "—", never
 *  the literal "Invalid Date" string. */
function formatQuoteTime(ts?: string): string {
  if (!ts) return "—";
  const d = new Date(ts);
  return Number.isNaN(d.getTime()) ? "—" : d.toLocaleTimeString();
}

/** Calm, stable badge per transport status — no rapid Disconnected/Stale flips.
 *  "polling"/"reconnecting" are healthy/transitional and use a neutral tone so a
 *  working REST fallback is never presented as a failure. */
const STATUS_BADGE: Record<TransportStatus, { label: string; cls: string } | null> = {
  live: { label: "Live", cls: "bg-accent-up/15 text-accent-up" },
  polling: { label: "Polling", cls: "bg-accent/15 text-accent" },
  reconnecting: { label: "Reconnecting", cls: "bg-ink-dim/15 text-ink-dim" },
  connecting: null, // startup — no alarming badge
  offline: { label: "Offline", cls: "bg-accent-down/20 text-accent-down" },
};

export function LiveQuotesPanel({ symbols }: { symbols: string[] }) {
  const { quotes, lastUpdate, transportStatus, hasEverReceivedData, error } =
    useLiveQuotes(symbols);
  // Stale is timestamp-driven (q.stale from the backend), independent of the
  // connection — so it does not flash on transient reconnects.
  const stale = quotes.some((q) => q.stale);

  const badge = STATUS_BADGE[transportStatus];

  const headerBadges = (
    <span className="ml-2 inline-flex gap-2 align-middle">
      {badge ? (
        <span className={`rounded px-1.5 py-0.5 text-[10px] font-medium ${badge.cls}`}>
          {badge.label}
        </span>
      ) : null}
      {stale ? (
        <span
          className="rounded bg-accent/15 px-1.5 py-0.5 text-[10px] font-medium text-accent"
          title="At least one quote is older than the freshness threshold"
        >
          Stale
        </span>
      ) : null}
    </span>
  );

  return (
    <Card
      title={
        <>
          Live quotes
          {headerBadges}
        </>
      }
      hint={
        lastUpdate
          ? `Last update ${formatQuoteTime(lastUpdate)}`
          : "Waiting for live data…"
      }
    >
      {quotes.length === 0 ? (
        <p className="text-xs text-ink-dim">
          {transportStatus === "offline" && error
            ? error
            : hasEverReceivedData
              ? "Waiting for live data…"
              : "Cache is cold — quotes will appear when the poller writes them."}
        </p>
      ) : (
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-xs text-ink-dim">
              <th className="py-1">Symbol</th>
              <th className="py-1 text-right">Price</th>
              <th className="py-1 text-right">Change</th>
              <th className="py-1 text-right">As of</th>
            </tr>
          </thead>
          <tbody>
            {quotes.map((q) => (
              <tr key={q.symbol} className="border-t border-border">
                <td className="py-1 font-mono">{q.symbol}</td>
                <td className="py-1 text-right font-mono">{formatNumber(q.price)}</td>
                <td
                  className={`py-1 text-right font-mono ${
                    q.change && q.change > 0
                      ? "text-accent-up"
                      : q.change && q.change < 0
                        ? "text-accent-down"
                        : "text-ink-muted"
                  }`}
                >
                  {formatNumber(q.change)}
                </td>
                <td
                  className={`py-1 text-right text-xs ${q.stale ? "text-accent" : "text-ink-dim"}`}
                  title={q.ts ?? undefined}
                >
                  {formatQuoteTime(q.ts)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </Card>
  );
}
