"use client";

import { Card } from "@/components/ui/Card";
import { Badge } from "@/components/ui/Badge";
import { EmptyState } from "@/components/ui/AsyncStates";
import { useBrokerAccount } from "@/hooks/useBrokerAccount";
import { formatVnd, formatNumber } from "@/lib/format";

/**
 * Read-only SSI broker account panel.
 *
 * Shows LIVE broker cash + holdings only when the backend reports a genuinely
 * connected, read-only SSI provider. In every other state (mock/dev,
 * unconfigured, error) it renders an honest message and NEVER displays
 * fabricated balances — the dashboard's own data stays the manual portfolio.
 */
export function BrokerAccountCard() {
  const { snapshot, loading, error } = useBrokerAccount();
  const cash = snapshot?.cash ?? null;
  const positions = snapshot?.positions ?? [];

  const hint = "Read-only SSI sync — no orders are ever placed from here.";

  if (loading) {
    return (
      <Card title="Broker account (SSI)" hint={hint}>
        <p className="text-xs text-ink-dim">Checking broker connection…</p>
      </Card>
    );
  }

  if (error) {
    return (
      <Card title="Broker account (SSI)" hint={hint}>
        <p className="text-xs text-ink-dim">
          Broker status unavailable. The dashboard continues to show your manual
          portfolio.
        </p>
      </Card>
    );
  }

  const isMock = !!snapshot?.mock;
  const isLive = snapshot?.connected === true;

  // Mock/dev: do NOT render the provider's fabricated numbers as real.
  if (isMock) {
    return (
      <Card
        title={
          <span className="inline-flex items-center gap-2">
            Broker account (SSI) <Badge tone="mock">Mock</Badge>
          </span>
        }
        hint={hint}
      >
        <p className="text-xs text-ink-dim">
          Broker sync is running in mock mode (development). Live SSI balances are
          not connected — the figures above come from your manual portfolio.
        </p>
      </Card>
    );
  }

  // SSI selected but not configured (no key / account / PIN).
  if (!isLive) {
    return (
      <Card
        title={
          <span className="inline-flex items-center gap-2">
            Broker account (SSI) <Badge tone="info">Not connected</Badge>
          </span>
        }
        hint={hint}
      >
        <p className="text-xs text-ink-dim">
          SSI read-only sync is not configured. The dashboard shows your manual
          portfolio. To connect, an operator must supply read-only SSI
          credentials (see docs/audit) — order placement remains disabled.
        </p>
      </Card>
    );
  }

  // Genuinely connected, read-only, real data.
  return (
    <Card
      title={
        <span className="inline-flex items-center gap-2">
          Broker account (SSI) <Badge tone="up">Live · read-only</Badge>
        </span>
      }
      hint={hint}
    >
      {cash ? (
        <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
          <Stat label="Cash" value={formatVnd(cash.cash_balance, { compact: true })} />
          <Stat label="Buying power" value={formatVnd(cash.buying_power, { compact: true })} />
          <Stat label="Withdrawable" value={formatVnd(cash.withdrawable_cash, { compact: true })} />
          <Stat label="Pending (T+2)" value={formatVnd(cash.pending_cash, { compact: true })} />
        </div>
      ) : null}

      <div className="mt-4">
        <p className="mb-2 text-xs font-medium text-ink">Holdings</p>
        {positions.length === 0 ? (
          <EmptyState>No broker holdings.</EmptyState>
        ) : (
          <table className="w-full text-xs">
            <thead className="text-ink-dim">
              <tr className="text-left">
                <th className="py-1">Symbol</th>
                <th className="py-1 text-right">Qty</th>
                <th className="py-1 text-right">Sellable</th>
                <th className="py-1 text-right">Avg cost</th>
                <th className="py-1 text-right">Mkt value</th>
                <th className="py-1 text-right">Unrealized</th>
              </tr>
            </thead>
            <tbody className="font-mono text-ink-muted">
              {positions.map((p) => (
                <tr key={p.symbol} className="border-t border-border">
                  <td className="py-1 text-ink">{p.symbol}</td>
                  <td className="py-1 text-right">{formatNumber(p.quantity)}</td>
                  <td className="py-1 text-right">{formatNumber(p.sellable_quantity)}</td>
                  <td className="py-1 text-right">{formatNumber(p.avg_cost)}</td>
                  <td className="py-1 text-right">
                    {p.market_value != null ? formatVnd(p.market_value, { compact: true }) : "—"}
                  </td>
                  <td
                    className={`py-1 text-right ${
                      p.unrealized_pnl != null && p.unrealized_pnl < 0
                        ? "text-accent-down"
                        : "text-accent-up"
                    }`}
                  >
                    {p.unrealized_pnl != null ? formatNumber(p.unrealized_pnl) : "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </Card>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-border bg-bg-panel px-3 py-2">
      <p className="text-[11px] text-ink-dim uppercase tracking-wider">{label}</p>
      <p className="mt-1 text-lg font-semibold text-ink font-mono">{value}</p>
    </div>
  );
}
