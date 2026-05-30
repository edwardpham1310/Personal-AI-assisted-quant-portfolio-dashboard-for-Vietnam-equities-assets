import { Card } from "@/components/ui/Card";
import { Badge } from "@/components/ui/Badge";
import { StatusPill, type StatusLevel } from "./StatusPill";
import type { ProviderHealth } from "@/hooks/useSystemStatus";

function levelFromProvider(p: ProviderHealth): StatusLevel {
  if (p.error) return "error";
  if (!p.ready) return "warn";
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

export function ProviderCard({ provider }: { provider: ProviderHealth }) {
  const level = levelFromProvider(provider);
  return (
    <Card
      title={
        <span className="flex items-center gap-2">
          <span>Market data provider</span>
          <StatusPill level={level} />
        </span>
      }
      hint="SSI FastConnect or deterministic mock"
    >
      <dl className="grid grid-cols-2 gap-y-1 text-xs">
        <dt className="text-ink-dim">Name</dt>
        <dd className="font-mono text-ink">
          {provider.name}
          {provider.mock ? (
            <Badge tone="mock" title="Deterministic mock provider">
              MOCK
            </Badge>
          ) : null}
        </dd>
        <dt className="text-ink-dim">Ready</dt>
        <dd className="text-ink">{provider.ready ? "yes" : "no"}</dd>
        <dt className="text-ink-dim">Token cached</dt>
        <dd className="text-ink">{provider.token_cached ? "yes" : "no"}</dd>
        <dt className="text-ink-dim">Last call</dt>
        <dd className="text-ink font-mono">{formatTs(provider.last_call_ts)}</dd>
        {provider.note ? (
          <>
            <dt className="text-ink-dim">Note</dt>
            <dd className="text-ink">{provider.note}</dd>
          </>
        ) : null}
        {provider.error ? (
          <>
            <dt className="text-ink-dim">Error</dt>
            <dd className="text-accent-down font-mono break-all">
              {provider.error}
            </dd>
          </>
        ) : null}
      </dl>
    </Card>
  );
}
