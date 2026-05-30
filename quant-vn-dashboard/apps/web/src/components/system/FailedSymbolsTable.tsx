import { Card } from "@/components/ui/Card";
import { Badge } from "@/components/ui/Badge";

export function FailedSymbolsTable({
  symbols,
  emptyMessage = "Every tracked symbol has a cached quote.",
}: {
  symbols: string[];
  emptyMessage?: string;
}) {
  return (
    <Card
      title="Symbols without a cached quote"
      hint="Provider returned no quote, or the poller hasn't run yet"
    >
      {symbols.length === 0 ? (
        <p className="text-ink-dim text-xs">{emptyMessage}</p>
      ) : (
        <ul className="flex flex-wrap gap-1.5">
          {symbols.map((s) => (
            <li key={s}>
              <Badge tone="warning">{s}</Badge>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}
