"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { Card } from "@/components/ui/Card";
import { EmptyState, ErrorState } from "@/components/ui/AsyncStates";
import { useApi } from "@/lib/api";
import { useWatchlistScanner } from "@/hooks/useScanner";
import { useWatchlistStream } from "@/hooks/useWatchlistStream";
import { ScannerTable, type ScannerRow } from "@/components/scanner/ScannerTable";
import { VN_EXCHANGES, type VnExchange } from "@quant-shared/constants/markets";

type WatchlistItem = {
  id: string;
  watchlist_id: string;
  symbol: string;
  exchange: VnExchange;
  display_order: number;
};

type Watchlist = {
  id: string;
  user_id: string;
  name: string;
  description: string | null;
  items: WatchlistItem[];
};

export default function WatchlistPage() {
  const api = useApi();
  const [lists, setLists] = useState<Watchlist[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [newName, setNewName] = useState("");
  const [selectedId, setSelectedId] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await api<Watchlist[]>("/watchlists");
      setLists(data);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load.");
    } finally {
      setLoading(false);
    }
  }, [api]);

  useEffect(() => {
    void load();
  }, [load]);

  // Keep the selection consistent: default to first list, drop if deleted.
  useEffect(() => {
    if (lists.length === 0) {
      setSelectedId(null);
      return;
    }
    if (!selectedId || !lists.some((l) => l.id === selectedId)) {
      setSelectedId(lists[0].id);
    }
  }, [lists, selectedId]);

  async function createList(e: React.FormEvent) {
    e.preventDefault();
    if (!newName.trim()) return;
    try {
      await api<Watchlist>("/watchlists", {
        method: "POST",
        body: JSON.stringify({ name: newName.trim() }),
      });
      setNewName("");
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Create failed.");
    }
  }

  const selected = useMemo(
    () => lists.find((l) => l.id === selectedId) ?? null,
    [lists, selectedId],
  );

  return (
    <div className="space-y-6">
      <header>
        <h1 className="text-xl font-semibold text-ink">Watchlist</h1>
        <p className="text-sm text-ink-dim mt-1">
          Symbols you want to follow. Stored per user under Supabase RLS.
        </p>
        <p className="text-[11px] text-ink-dim mt-2">
          Research signals · not financial advice · no orders placed.
        </p>
      </header>

      <Card title="Create a new watchlist">
        <form onSubmit={createList} className="flex gap-2">
          <input
            value={newName}
            onChange={(e) => setNewName(e.target.value)}
            placeholder="e.g. VN30 large caps"
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

      {loading ? (
        <Card title="Loading…">
          <p>Fetching watchlists.</p>
        </Card>
      ) : error ? (
        <Card title="Could not load watchlists" hint={error}>
          <button onClick={load} className="text-xs text-accent hover:underline">
            Retry
          </button>
        </Card>
      ) : lists.length === 0 ? (
        <Card title="No watchlists yet">
          <p>Create one above to get started.</p>
        </Card>
      ) : (
        <>
          {lists.length > 1 ? (
            <Card title="Select a watchlist">
              <label className="flex items-center gap-2 text-sm">
                <span className="text-ink-dim">Showing</span>
                <select
                  value={selectedId ?? ""}
                  onChange={(e) => setSelectedId(e.target.value || null)}
                  aria-label="Select watchlist"
                  className="rounded border border-border bg-bg px-2 py-1 text-sm text-ink"
                >
                  {lists.map((wl) => (
                    <option key={wl.id} value={wl.id}>
                      {wl.name} ({wl.items.length})
                    </option>
                  ))}
                </select>
              </label>
            </Card>
          ) : null}

          {selected ? <WatchlistCard watchlist={selected} reload={load} /> : null}
        </>
      )}
    </div>
  );
}

function WatchlistCard({
  watchlist,
  reload,
}: {
  watchlist: Watchlist;
  reload: () => Promise<void>;
}) {
  const api = useApi();
  const [symbol, setSymbol] = useState("");
  const [exchange, setExchange] = useState<VnExchange>("HOSE");
  const [busy, setBusy] = useState(false);

  const scanner = useWatchlistScanner(watchlist.id);
  const stream = useWatchlistStream(watchlist.id);

  const rows: ScannerRow[] = useMemo(() => {
    const liveBySymbol = new Map(stream.quotes.map((q) => [q.symbol.toUpperCase(), q]));
    return scanner.results.map((r) => {
      const live = liveBySymbol.get(r.symbol.toUpperCase());
      return {
        ...r,
        live_price: live ? live.price : null,
        live_stale: live ? live.stale : undefined,
      };
    });
  }, [scanner.results, stream.quotes]);

  async function addItem(e: React.FormEvent) {
    e.preventDefault();
    if (!symbol.trim()) return;
    setBusy(true);
    try {
      await api(`/watchlists/${watchlist.id}/items`, {
        method: "POST",
        body: JSON.stringify({ symbol: symbol.trim().toUpperCase(), exchange }),
      });
      setSymbol("");
      await reload();
      await scanner.refresh();
    } finally {
      setBusy(false);
    }
  }

  async function removeItem(itemId: string) {
    await api(`/watchlists/${watchlist.id}/items/${itemId}`, {
      method: "DELETE",
    });
    await reload();
    await scanner.refresh();
  }

  async function removeBySymbol(sym: string) {
    const match = watchlist.items.find((it) => it.symbol.toUpperCase() === sym.toUpperCase());
    if (!match) return;
    await removeItem(match.id);
  }

  return (
    <Card title={watchlist.name} hint={watchlist.description ?? undefined}>
      <form onSubmit={addItem} className="mb-4 flex gap-2">
        <input
          value={symbol}
          onChange={(e) => setSymbol(e.target.value)}
          placeholder="Symbol (e.g. FPT)"
          className="flex-1 rounded border border-border bg-bg px-2 py-1 text-sm text-ink uppercase"
        />
        <select
          value={exchange}
          onChange={(e) => setExchange(e.target.value as VnExchange)}
          className="rounded border border-border bg-bg px-2 py-1 text-sm text-ink"
        >
          {VN_EXCHANGES.map((x) => (
            <option key={x}>{x}</option>
          ))}
        </select>
        <button
          type="submit"
          disabled={busy}
          className="rounded border border-border bg-bg-subtle px-3 py-1 text-sm text-ink hover:border-accent disabled:opacity-50"
        >
          Add
        </button>
      </form>

      {watchlist.items.length === 0 ? (
        <EmptyState>Add a symbol to see signals.</EmptyState>
      ) : (
        <>
          <table className="mb-4 w-full text-sm">
            <thead>
              <tr className="text-left text-xs text-ink-dim">
                <th className="py-1">Symbol</th>
                <th className="py-1">Exchange</th>
                <th className="py-1" />
              </tr>
            </thead>
            <tbody>
              {watchlist.items.map((it) => (
                <tr key={it.id} className="border-t border-border">
                  <td className="py-1 font-mono">{it.symbol}</td>
                  <td className="py-1">{it.exchange}</td>
                  <td className="py-1 text-right">
                    <button
                      onClick={() => removeItem(it.id)}
                      className="text-xs text-ink-muted hover:text-accent-down"
                    >
                      Remove
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>

          <div className="mt-2 border-t border-border pt-4">
            <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
              <div>
                <h3 className="text-sm font-medium text-ink">Signal scanner</h3>
                <p className="text-[11px] text-ink-dim">
                  Research signals · not financial advice · no orders placed.
                </p>
              </div>
              <div className="flex items-center gap-3 text-[11px] text-ink-dim">
                {stream.connected ? (
                  <span className="rounded bg-accent-up/15 px-1.5 py-0.5 text-accent-up">Live</span>
                ) : (
                  <span className="rounded bg-bg-subtle px-1.5 py-0.5 text-ink-muted">
                    Snapshot
                  </span>
                )}
                {scanner.loading ? <span>Refreshing…</span> : null}
                <button
                  type="button"
                  onClick={() => void scanner.refresh()}
                  disabled={scanner.loading}
                  className="rounded border border-border bg-bg-subtle px-2 py-1 text-xs text-ink hover:border-accent disabled:opacity-50"
                >
                  Refresh signals
                </button>
              </div>
            </div>

            {scanner.error ? (
              <ErrorState
                message={`Scanner error: ${scanner.error}`}
                onRetry={() => void scanner.refresh()}
              />
            ) : null}

            <ScannerTable rows={rows} onRemove={removeBySymbol} />
          </div>
        </>
      )}
    </Card>
  );
}
