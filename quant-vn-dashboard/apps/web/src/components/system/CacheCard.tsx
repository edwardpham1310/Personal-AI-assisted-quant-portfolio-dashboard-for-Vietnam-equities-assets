import { Card } from "@/components/ui/Card";
import { StatusPill, type StatusLevel } from "./StatusPill";
import type { CacheHealth } from "@/hooks/useSystemStatus";

function levelFromCache(c: CacheHealth): StatusLevel {
  if (!c.healthy) return "error";
  if (c.last_poll_ok === false) return "warn";
  return "ok";
}

function formatTs(ts: string | null): string {
  if (!ts) return "never";
  try {
    return new Date(ts).toLocaleString();
  } catch {
    return ts;
  }
}

export function CacheCard({ cache }: { cache: CacheHealth }) {
  const level = levelFromCache(cache);
  return (
    <Card
      title={
        <span className="flex items-center gap-2">
          <span>Hot cache</span>
          <StatusPill level={level} />
        </span>
      }
      hint="Redis if configured, else in-memory"
    >
      <dl className="grid grid-cols-2 gap-y-1 text-xs">
        <dt className="text-ink-dim">Backend</dt>
        <dd className="font-mono text-ink">{cache.name}</dd>
        <dt className="text-ink-dim">Configured</dt>
        <dd className="text-ink">{cache.configured ? "yes" : "no (in-mem fallback)"}</dd>
        <dt className="text-ink-dim">Ping</dt>
        <dd className="text-ink">{cache.healthy ? "ok" : "failed"}</dd>
        <dt className="text-ink-dim">Last poll</dt>
        <dd className="text-ink font-mono">{formatTs(cache.last_poll_ts)}</dd>
        {cache.last_poll_error ? (
          <>
            <dt className="text-ink-dim">Poll error</dt>
            <dd className="text-accent-down font-mono break-all">{cache.last_poll_error}</dd>
          </>
        ) : null}
      </dl>
    </Card>
  );
}
