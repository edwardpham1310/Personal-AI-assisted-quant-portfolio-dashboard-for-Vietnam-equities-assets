"use client";

import { useCallback, useEffect, useState } from "react";
import { Card } from "@/components/ui/Card";
import { Badge } from "@/components/ui/Badge";
import { ErrorState, EmptyState } from "@/components/ui/AsyncStates";
import { useApi } from "@/lib/api";
import { usePortfolioSummary } from "@/hooks/usePortfolioSummary";
import { usePortfolioPositions } from "@/hooks/usePortfolioPositions";
import { PositionTable } from "@/components/portfolio/PositionTable";
import { PositionForm } from "@/components/portfolio/PositionForm";
import { AllocationDonut } from "@/components/portfolio/AllocationDonut";
import { StrategyAllocationDonut } from "@/components/portfolio/StrategyAllocationDonut";
import { PnlBySymbolBar } from "@/components/portfolio/PnlBySymbolBar";
import { PortfolioVsVnindexPlaceholder } from "@/components/portfolio/PortfolioVsVnindexPlaceholder";
import { formatVnd, formatNumber } from "@/lib/format";
import type { EnrichedPosition, PositionCreate, PositionUpdate } from "@/hooks/portfolio-types";

type Account = {
  id: string;
  user_id: string;
  name: string;
  broker: string;
  currency: string;
};

export default function PortfolioPage() {
  const api = useApi();
  const summary = usePortfolioSummary();
  const positions = usePortfolioPositions();

  const [accounts, setAccounts] = useState<Account[]>([]);
  const [accountsLoading, setAccountsLoading] = useState(true);
  const [accountsError, setAccountsError] = useState<string | null>(null);
  const [newAccount, setNewAccount] = useState("");

  const [editing, setEditing] = useState<EnrichedPosition | null>(null);
  const [showAddForm, setShowAddForm] = useState(false);
  const [formBusy, setFormBusy] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);

  const loadAccounts = useCallback(async () => {
    setAccountsLoading(true);
    setAccountsError(null);
    try {
      const data = await api<{ accounts: Account[] }>("/portfolio/manual");
      setAccounts(data.accounts);
    } catch (e) {
      setAccountsError(e instanceof Error ? e.message : "Failed to load accounts.");
    } finally {
      setAccountsLoading(false);
    }
  }, [api]);

  useEffect(() => {
    void loadAccounts();
  }, [loadAccounts]);

  async function createAccount(e: React.FormEvent) {
    e.preventDefault();
    if (!newAccount.trim()) return;
    try {
      await api<Account>("/portfolio/manual/accounts", {
        method: "POST",
        body: JSON.stringify({ name: newAccount.trim() }),
      });
      setNewAccount("");
      await loadAccounts();
    } catch (e) {
      setAccountsError(e instanceof Error ? e.message : "Create failed.");
    }
  }

  const handlePositionSubmit = useCallback(
    async (
      payload: PositionCreate | PositionUpdate,
      mode: "create" | "update",
      positionId: string | null,
    ) => {
      setFormBusy(true);
      setActionError(null);
      try {
        if (mode === "create") {
          await api<EnrichedPosition>("/portfolio/positions", {
            method: "POST",
            body: JSON.stringify(payload),
          });
          setShowAddForm(false);
        } else if (positionId) {
          await api<EnrichedPosition>(`/portfolio/positions/${positionId}`, {
            method: "PUT",
            body: JSON.stringify(payload),
          });
          setEditing(null);
        }
        await Promise.all([positions.refresh(), summary.refresh()]);
      } catch (e) {
        setActionError(e instanceof Error ? e.message : "Save failed.");
      } finally {
        setFormBusy(false);
      }
    },
    [api, positions, summary],
  );

  async function deletePosition(p: EnrichedPosition) {
    setActionError(null);
    try {
      await api(`/portfolio/positions/${p.id}`, { method: "DELETE" });
      await Promise.all([positions.refresh(), summary.refresh()]);
    } catch (e) {
      setActionError(e instanceof Error ? e.message : "Delete failed.");
    }
  }

  async function refreshAll() {
    await Promise.all([summary.refresh(), positions.refresh()]);
  }

  return (
    <div className="space-y-6">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold text-ink">Portfolio</h1>
          <p className="text-[11px] text-ink-dim mt-2">
            Research dashboard · Manual entry · No orders placed.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => void refreshAll()}
            disabled={summary.loading || positions.loading}
            className="rounded border border-border bg-bg-subtle px-2 py-1 text-xs text-ink hover:border-accent disabled:opacity-50"
          >
            {summary.loading || positions.loading ? "Refreshing…" : "Refresh"}
          </button>
          <button
            type="button"
            disabled
            title="Phase 2 — SSI read-only sync is not yet wired up."
            aria-disabled
            className="inline-flex cursor-not-allowed items-center gap-1 rounded border border-border bg-bg-subtle px-2 py-1 text-xs text-ink-dim opacity-60"
          >
            Sync from SSI
            <Badge tone="info">Phase 2</Badge>
          </button>
        </div>
      </header>

      {/* Account context */}
      <Card title="Account" hint="The default account is used for /portfolio/* endpoints.">
        {accountsLoading ? (
          <p className="text-xs text-ink-dim">Loading accounts…</p>
        ) : accountsError ? (
          <ErrorState message={accountsError} onRetry={() => void loadAccounts()} />
        ) : accounts.length === 0 ? (
          <p className="text-xs text-ink-dim">
            No account yet. Create one below to start tracking positions.
          </p>
        ) : accounts.length === 1 ? (
          <p className="text-xs text-ink-muted">
            Default account · <span className="text-ink">{accounts[0].name}</span> (
            {accounts[0].broker} · {accounts[0].currency})
          </p>
        ) : (
          <div className="flex flex-col gap-1 text-xs">
            <span className="text-ink-dim">
              Multiple accounts found — the API uses the default account.
            </span>
            <select
              aria-label="Active account (read-only display)"
              disabled
              defaultValue={accounts[0].id}
              className="w-fit rounded border border-border bg-bg px-2 py-1 text-sm text-ink"
            >
              {accounts.map((a) => (
                <option key={a.id} value={a.id}>
                  {a.name} · {a.broker}
                </option>
              ))}
            </select>
          </div>
        )}
      </Card>

      <Card title="Create an account">
        <form onSubmit={createAccount} className="flex gap-2">
          <input
            value={newAccount}
            onChange={(e) => setNewAccount(e.target.value)}
            placeholder="e.g. Main SSI account"
            aria-label="New account name"
            className="flex-1 rounded border border-border bg-bg px-3 py-2 text-sm text-ink"
          />
          <button
            type="submit"
            className="rounded bg-accent px-3 py-2 text-sm font-medium text-white hover:opacity-90"
          >
            Create
          </button>
        </form>
      </Card>

      {/* Summary KPIs */}
      {summary.error ? (
        <ErrorState
          message={`Summary error: ${summary.error}`}
          onRetry={() => void summary.refresh()}
        />
      ) : null}

      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <div className="rounded-lg border border-border bg-bg-panel px-4 py-3">
          <p className="text-xs text-ink-dim uppercase tracking-wider">Positions</p>
          <p className="mt-1 text-2xl font-semibold text-ink font-mono">
            {summary.summary?.position_count ?? 0}
          </p>
        </div>
        <div className="rounded-lg border border-border bg-bg-panel px-4 py-3">
          <p className="text-xs text-ink-dim uppercase tracking-wider">Total cost</p>
          <p className="mt-1 text-2xl font-semibold text-ink font-mono">
            {summary.summary ? formatVnd(summary.summary.total_cost, { compact: true }) : "—"}
          </p>
        </div>
        <div className="rounded-lg border border-border bg-bg-panel px-4 py-3">
          <p className="text-xs text-ink-dim uppercase tracking-wider">Market value</p>
          <p className="mt-1 text-2xl font-semibold text-ink font-mono">
            {summary.summary
              ? formatVnd(summary.summary.total_market_value, { compact: true })
              : "—"}
          </p>
        </div>
        <div className="rounded-lg border border-border bg-bg-panel px-4 py-3">
          <p className="text-xs text-ink-dim uppercase tracking-wider">Unrealized PnL</p>
          <p
            className={`mt-1 text-2xl font-semibold font-mono ${
              summary.summary?.total_unrealized_pnl
                ? summary.summary.total_unrealized_pnl >= 0
                  ? "text-accent-up"
                  : "text-accent-down"
                : "text-ink"
            }`}
          >
            {summary.summary
              ? `${summary.summary.total_unrealized_pnl >= 0 ? "+" : ""}${formatNumber(summary.summary.total_unrealized_pnl)}`
              : "—"}
          </p>
          {summary.summary?.total_unrealized_pnl_pct != null ? (
            <p className="mt-1 text-xs text-ink-dim font-mono">
              {summary.summary.total_unrealized_pnl_pct >= 0 ? "+" : ""}
              {summary.summary.total_unrealized_pnl_pct.toFixed(2)}%
            </p>
          ) : null}
        </div>
      </div>

      {/* Add position */}
      <Card title="Positions" hint="Manual entry — research only.">
        {actionError ? (
          <div className="mb-2">
            <ErrorState message={actionError} />
          </div>
        ) : null}

        <div className="mb-3 flex items-center justify-between">
          <button
            type="button"
            onClick={() => {
              setShowAddForm((v) => !v);
              setEditing(null);
            }}
            className="rounded border border-border bg-bg-subtle px-2 py-1 text-xs text-ink hover:border-accent"
          >
            {showAddForm ? "Close form" : "Add position"}
          </button>
          {positions.loading ? <span className="text-[11px] text-ink-dim">Refreshing…</span> : null}
        </div>

        {showAddForm ? (
          <div className="mb-4 rounded border border-border bg-bg-subtle p-3">
            <PositionForm
              onSubmit={handlePositionSubmit}
              onCancel={() => setShowAddForm(false)}
              busy={formBusy}
            />
          </div>
        ) : null}

        {editing ? (
          <div className="mb-4 rounded border border-accent/40 bg-accent/5 p-3">
            <p className="mb-2 text-xs text-ink-muted">
              Editing <span className="font-mono text-ink">{editing.symbol}</span>
            </p>
            <PositionForm
              initial={editing}
              onSubmit={handlePositionSubmit}
              onCancel={() => setEditing(null)}
              busy={formBusy}
            />
          </div>
        ) : null}

        {positions.error ? (
          <ErrorState
            message={`Positions error: ${positions.error}`}
            onRetry={() => void positions.refresh()}
          />
        ) : positions.loading && positions.positions.length === 0 ? (
          <EmptyState>Loading positions…</EmptyState>
        ) : (
          <PositionTable rows={positions.positions} onEdit={setEditing} onDelete={deletePosition} />
        )}
      </Card>

      {/* Charts */}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <AllocationDonut positions={positions.positions} />
        <StrategyAllocationDonut summary={summary.summary} />
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <PnlBySymbolBar positions={positions.positions} />
        <PortfolioVsVnindexPlaceholder />
      </div>
    </div>
  );
}
