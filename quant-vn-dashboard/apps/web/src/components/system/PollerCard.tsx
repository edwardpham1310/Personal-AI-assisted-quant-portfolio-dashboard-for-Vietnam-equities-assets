import { Card } from "@/components/ui/Card";
import { StatusPill, type StatusLevel } from "./StatusPill";
import type { PollerHealth } from "@/hooks/useSystemStatus";

function levelFromPoller(p: PollerHealth): StatusLevel {
  if (!p.enabled) return "warn";
  if (!p.running) return "error";
  return "ok";
}

export function PollerCard({ poller }: { poller: PollerHealth }) {
  return (
    <Card
      title={
        <span className="flex items-center gap-2">
          <span>Market poller</span>
          <StatusPill level={levelFromPoller(poller)} />
        </span>
      }
      hint="Background loop that fills the hot cache"
    >
      <dl className="grid grid-cols-2 gap-y-1 text-xs">
        <dt className="text-ink-dim">Enabled</dt>
        <dd className="text-ink">{poller.enabled ? "yes" : "no"}</dd>
        <dt className="text-ink-dim">Running</dt>
        <dd className="text-ink">{poller.running ? "yes" : "no"}</dd>
        <dt className="text-ink-dim">Active symbols</dt>
        <dd className="text-ink font-mono">{poller.active_symbols_count}</dd>
      </dl>
      {!poller.enabled ? (
        <p className="mt-2 text-[11px] text-ink-dim">
          Set <code className="font-mono text-ink">ENABLE_MARKET_POLLER=true</code> to start filling
          the cache automatically.
        </p>
      ) : null}
    </Card>
  );
}
