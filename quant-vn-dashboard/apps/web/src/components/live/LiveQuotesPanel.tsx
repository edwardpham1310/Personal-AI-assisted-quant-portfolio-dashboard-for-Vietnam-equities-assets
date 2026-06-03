"use client";

import { Card } from "@/components/ui/Card";
import { useLiveQuotes } from "@/hooks/useLiveQuotes";
import { formatNumber } from "@/lib/format";

export function LiveQuotesPanel({ symbols }: { symbols: string[] }) {
  const { quotes, lastUpdate, connected, error } = useLiveQuotes(symbols);
  const stale = quotes.some((q) => q.stale);

  const headerBadges = (
    <span className="ml-2 inline-flex gap-2 align-middle">
      {!connected ? (
        <span
          className="rounded bg-accent-down/20 px-1.5 py-0.5 text-[10px] font-medium text-accent-down"
          title={error ?? "Stream disconnected — falling back to polling"}
        >
          Disconnected
        </span>
      ) : (
        <span className="rounded bg-accent-up/15 px-1.5 py-0.5 text-[10px] font-medium text-accent-up">
          Live
        </span>
      )}
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
          ? `Last update ${new Date(lastUpdate).toLocaleTimeString()}`
          : "Awaiting first update…"
      }
    >
      {quotes.length === 0 ? (
        <p className="text-xs text-ink-dim">
          {error ? error : "Cache is cold — quotes will appear when the poller writes them."}
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
                  title={q.ts}
                >
                  {new Date(q.ts).toLocaleTimeString()}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </Card>
  );
}
