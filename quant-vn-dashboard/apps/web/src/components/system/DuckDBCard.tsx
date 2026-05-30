import { Card } from "@/components/ui/Card";
import { StatusPill, type StatusLevel } from "./StatusPill";
import type { DuckDBHealth } from "@/hooks/useSystemStatus";

function formatBytes(n: number | null): string {
  if (n == null) return "—";
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  if (n < 1024 * 1024 * 1024) return `${(n / (1024 * 1024)).toFixed(1)} MB`;
  return `${(n / (1024 * 1024 * 1024)).toFixed(2)} GB`;
}

function levelFromDuckDB(d: DuckDBHealth): StatusLevel {
  if (!d.configured) return "warn";
  if (!d.exists) return "warn";
  return "ok";
}

export function DuckDBCard({ duckdb }: { duckdb: DuckDBHealth }) {
  return (
    <Card
      title={
        <span className="flex items-center gap-2">
          <span>DuckDB warehouse</span>
          <StatusPill level={levelFromDuckDB(duckdb)} />
        </span>
      }
      hint="Local OHLCV / signal store"
    >
      <dl className="grid grid-cols-2 gap-y-1 text-xs">
        <dt className="text-ink-dim">Configured</dt>
        <dd className="text-ink">{duckdb.configured ? "yes" : "no"}</dd>
        <dt className="text-ink-dim">Path</dt>
        <dd className="font-mono text-ink break-all">{duckdb.path ?? "—"}</dd>
        <dt className="text-ink-dim">Exists</dt>
        <dd className="text-ink">{duckdb.exists ? "yes" : "no"}</dd>
        <dt className="text-ink-dim">Size</dt>
        <dd className="font-mono text-ink">{formatBytes(duckdb.size_bytes)}</dd>
      </dl>
    </Card>
  );
}
