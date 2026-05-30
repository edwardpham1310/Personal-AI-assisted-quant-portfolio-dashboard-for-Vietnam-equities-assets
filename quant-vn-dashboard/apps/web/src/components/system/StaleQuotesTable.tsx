import { Card } from "@/components/ui/Card";

export type StaleQuoteRow = {
  symbol: string;
  ts?: string | null;
  age_seconds?: number;
  source?: string | null;
  stale?: boolean;
};

export function StaleQuotesTable({
  rows,
  emptyMessage = "No stale quotes — all tracked symbols are fresh.",
}: {
  rows: StaleQuoteRow[];
  emptyMessage?: string;
}) {
  return (
    <Card title="Stale quotes" hint="Cached quotes older than the freshness threshold">
      {rows.length === 0 ? (
        <p className="text-ink-dim text-xs">{emptyMessage}</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="min-w-full text-xs">
            <thead>
              <tr className="text-left text-ink-dim border-b border-border">
                <th className="py-1 pr-3 font-medium">Symbol</th>
                <th className="py-1 pr-3 font-medium">Age</th>
                <th className="py-1 pr-3 font-medium">Last seen</th>
                <th className="py-1 pr-3 font-medium">Source</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.symbol} className="border-b border-border/40">
                  <td className="py-1 pr-3 font-mono text-ink">{r.symbol}</td>
                  <td className="py-1 pr-3 text-accent-down font-mono">
                    {r.age_seconds != null ? `${r.age_seconds}s` : "—"}
                  </td>
                  <td className="py-1 pr-3 font-mono text-ink-muted">
                    {r.ts ? new Date(r.ts).toLocaleString() : "—"}
                  </td>
                  <td className="py-1 pr-3 text-ink-muted">{r.source ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}
