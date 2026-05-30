"use client";

import { useCallback, useState } from "react";
import { Card } from "@/components/ui/Card";
import { Badge } from "@/components/ui/Badge";
import { EnvironmentChecklist } from "@/components/system/EnvironmentChecklist";
import { env } from "@/lib/env";
import { useSystemStatus } from "@/hooks/useSystemStatus";

type HealthPayload = {
  status: "ok" | "degraded" | "down";
  env: string;
  version: string;
  app_uptime_seconds?: number | null;
  cache_reachable?: boolean;
  settings_loaded?: boolean;
  checked_at?: string;
};

export default function SystemSettingsPage() {
  const status = useSystemStatus();
  const [health, setHealth] = useState<HealthPayload | null>(null);
  const [healthLoading, setHealthLoading] = useState(false);
  const [healthError, setHealthError] = useState<string | null>(null);

  const runHealthCheck = useCallback(async () => {
    setHealthLoading(true);
    setHealthError(null);
    try {
      // The /system/health endpoint is public — no Authorization header needed.
      const res = await fetch(`${env.apiBaseUrl}/system/health`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const body = (await res.json()) as HealthPayload;
      setHealth(body);
    } catch (err) {
      setHealthError(err instanceof Error ? err.message : "Health check failed");
    } finally {
      setHealthLoading(false);
    }
  }, []);

  const toneFor = (s: HealthPayload["status"]) =>
    s === "ok" ? "up" : s === "degraded" ? "warning" : "down";

  return (
    <div className="space-y-6">
      <header>
        <h1 className="text-xl font-semibold text-ink">System settings</h1>
        <p className="text-sm text-ink-dim mt-1">
          Environment + readiness checks for the API. Run-time secrets are never
          surfaced — only their configured/missing state.
        </p>
      </header>

      <EnvironmentChecklist missingSecrets={status.data?.missing_secrets ?? []} />

      <Card title="Run health check" hint="Calls the public /system/health endpoint">
        <div className="flex items-center gap-3">
          <button
            type="button"
            onClick={() => void runHealthCheck()}
            disabled={healthLoading}
            className="rounded border border-border bg-bg-panel px-3 py-1.5 text-xs text-ink hover:bg-bg disabled:opacity-50"
          >
            {healthLoading ? "Checking…" : "Run health check"}
          </button>
          {health ? (
            <Badge tone={toneFor(health.status)}>{health.status.toUpperCase()}</Badge>
          ) : null}
        </div>

        {healthError ? (
          <p className="mt-3 text-xs text-accent-down">{healthError}</p>
        ) : null}

        {health ? (
          <dl className="mt-3 grid grid-cols-2 gap-y-1 text-xs">
            <dt className="text-ink-dim">Status</dt>
            <dd className="font-mono text-ink">{health.status}</dd>
            <dt className="text-ink-dim">Env</dt>
            <dd className="font-mono text-ink">{health.env}</dd>
            <dt className="text-ink-dim">Version</dt>
            <dd className="font-mono text-ink">{health.version}</dd>
            {health.app_uptime_seconds != null ? (
              <>
                <dt className="text-ink-dim">Uptime</dt>
                <dd className="font-mono text-ink">
                  {Math.round(health.app_uptime_seconds)}s
                </dd>
              </>
            ) : null}
            {typeof health.cache_reachable === "boolean" ? (
              <>
                <dt className="text-ink-dim">Cache reachable</dt>
                <dd className="font-mono text-ink">
                  {health.cache_reachable ? "yes" : "no"}
                </dd>
              </>
            ) : null}
            {health.checked_at ? (
              <>
                <dt className="text-ink-dim">Checked at</dt>
                <dd className="font-mono text-ink">
                  {new Date(health.checked_at).toLocaleString()}
                </dd>
              </>
            ) : null}
          </dl>
        ) : null}
      </Card>
    </div>
  );
}
