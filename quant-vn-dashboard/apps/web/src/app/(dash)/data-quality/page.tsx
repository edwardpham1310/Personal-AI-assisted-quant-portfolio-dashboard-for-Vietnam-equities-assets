"use client";

import { useMemo } from "react";
import { Card } from "@/components/ui/Card";
import { KpiCard } from "@/components/ui/KpiCard";
import { CacheCard } from "@/components/system/CacheCard";
import { DuckDBCard } from "@/components/system/DuckDBCard";
import { EnvironmentChecklist } from "@/components/system/EnvironmentChecklist";
import { FailedSymbolsTable } from "@/components/system/FailedSymbolsTable";
import { PollerCard } from "@/components/system/PollerCard";
import { ProviderCard } from "@/components/system/ProviderCard";
import { StaleQuotesTable } from "@/components/system/StaleQuotesTable";
import { SupabaseCard } from "@/components/system/SupabaseCard";
import { useDataQuality } from "@/hooks/useDataQuality";
import { useSystemStatus } from "@/hooks/useSystemStatus";

export default function DataQualityPage() {
  const status = useSystemStatus();
  const dq = useDataQuality();

  const lastSync = useMemo(() => {
    const ts = dq.data?.last_successful_sync ?? null;
    if (!ts) return "never";
    try {
      return new Date(ts).toLocaleString();
    } catch {
      return ts;
    }
  }, [dq.data?.last_successful_sync]);

  const refreshing = status.loading || dq.loading;

  return (
    <div className="space-y-6">
      <header className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-xl font-semibold text-ink">Data Quality</h1>
          <p className="text-sm text-ink-dim mt-1">
            Cache freshness, provider health, and pipeline observability for
            the SSI gateway. Research dashboard — no orders placed.
          </p>
        </div>
        <button
          type="button"
          onClick={() => {
            void status.refresh();
            void dq.refresh();
          }}
          disabled={refreshing}
          className="rounded border border-border bg-bg-panel px-3 py-1.5 text-xs text-ink hover:bg-bg disabled:opacity-50"
        >
          {refreshing ? "Refreshing…" : "Refresh"}
        </button>
      </header>

      <div className="rounded border border-amber-500/30 bg-amber-500/5 px-3 py-2 text-xs text-amber-300">
        Research dashboard — operational data only. Every error string is
        redacted on the API side before it reaches this view.
      </div>

      {/* Phase 2.5 critical banner: production must never serve mock data. */}
      {status.data?.app_env === "production" &&
      status.data?.provider?.mode === "MOCK_TEST_ONLY" ? (
        <div
          role="alert"
          className="rounded border border-accent-down/60 bg-accent-down/10 px-3 py-2 text-xs text-accent-down"
          data-testid="production-mock-banner"
        >
          <strong className="font-semibold">CRITICAL:</strong> Production is
          serving MOCK_TEST_ONLY market data. The backend startup guard
          should have prevented this — investigate immediately and set
          <code className="ml-1 font-mono">SSI_USE_MOCK=false</code> +
          populate SSI credentials. Recommendations and quotes shown on
          the dashboard are NOT backed by real SSI.
        </div>
      ) : null}

      {/* Phase 2.5 production-readiness checklist driven by provider flags. */}
      {status.data?.provider?.production_ready === false &&
      status.data?.provider?.mode === "REAL" ? (
        <div
          role="alert"
          className="rounded border border-amber-500/50 bg-amber-500/10 px-3 py-2 text-xs text-amber-200"
          data-testid="production-not-ready-banner"
        >
          Provider is in REAL mode but not production-ready —{" "}
          <code className="font-mono">
            {status.data.provider.status_code ?? "UNKNOWN"}
          </code>
          {status.data.provider.last_error_sanitized ? (
            <span> — last error: {status.data.provider.last_error_sanitized}</span>
          ) : null}
          . Check SSI credentials, network, and rate-limit headroom.
        </div>
      ) : null}

      {/* ── KPIs ──────────────────────────────────────────────────────── */}
      <div className="grid grid-cols-1 md:grid-cols-4 gap-3">
        <KpiCard
          label="Tracked symbols"
          value={dq.data?.total_tracked_symbols ?? "—"}
          hint="Core + active subscriptions"
          loading={dq.loading && !dq.data}
        />
        <KpiCard
          label="Stale quotes"
          value={dq.data?.stale_quote_count ?? "—"}
          hint="Older than freshness threshold"
          tone={
            dq.data && dq.data.stale_quote_count > 0 ? "down" : "neutral"
          }
          loading={dq.loading && !dq.data}
        />
        <KpiCard
          label="Cache misses"
          value={dq.data?.cache_misses ?? "—"}
          hint="Symbols with no cached quote"
          tone={
            dq.data && (dq.data.cache_misses ?? 0) > 0 ? "down" : "neutral"
          }
          loading={dq.loading && !dq.data}
        />
        <KpiCard
          label="Last successful sync"
          value={lastSync}
          hint={`Provider errors: ${dq.data?.provider_errors ?? 0}`}
          loading={dq.loading && !dq.data}
        />
      </div>

      {/* ── Component cards ──────────────────────────────────────────── */}
      {status.error ? (
        <Card title="Could not load system status" hint={status.error}>
          <button
            type="button"
            onClick={() => void status.refresh()}
            className="text-xs text-accent hover:underline"
          >
            Retry
          </button>
        </Card>
      ) : status.data ? (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          <ProviderCard provider={status.data.provider} />
          <CacheCard cache={status.data.cache} />
          <PollerCard poller={status.data.poller} />
          <SupabaseCard supabase={status.data.supabase} />
          <DuckDBCard duckdb={status.data.duckdb} />
          <EnvironmentChecklist missingSecrets={status.data.missing_secrets} />
        </div>
      ) : (
        <Card title="Loading system status…">
          <p className="text-ink-dim text-xs">
            Fetching cache, provider, and poller health.
          </p>
        </Card>
      )}

      {/* ── Tables ──────────────────────────────────────────────────── */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <StaleQuotesTable
          rows={(dq.data?.stale_quote_rows ?? []).filter((r) => r.stale)}
        />
        <FailedSymbolsTable
          symbols={dq.data?.symbols_without_quote ?? []}
        />
      </div>

      {dq.data?.notes && dq.data.notes.length > 0 ? (
        <Card title="Notes" hint="Hints surfaced by the data-quality service">
          <ul className="list-disc list-inside text-xs text-ink-muted space-y-1">
            {dq.data.notes.map((n, idx) => (
              <li key={idx}>{n}</li>
            ))}
          </ul>
        </Card>
      ) : null}
    </div>
  );
}
