"use client";

import { Card } from "@/components/ui/Card";
import { EmptyState } from "@/components/ui/AsyncStates";
import { Skeleton } from "@/components/ui/Skeleton";
import { useAssetsSettlement } from "@/hooks/useAssetsSettlement";
import { formatVnd } from "@/lib/format";

/**
 * Pending T+2 settlements (cash settling from sells, shares settling from
 * buys), ascending by date. Derived from real trade settlement dates;
 * honest-empty when none are pending.
 */
export function SettlementAlertsCard() {
  const { data, loading, error } = useAssetsSettlement();
  const alerts = data?.alerts ?? [];

  return (
    <Card title="Settlement alerts" hint="Pending T+2 settlements — read-only">
      {loading && !data ? (
        <Skeleton height={120} />
      ) : error ? (
        <p className="text-xs text-accent-down">{error}</p>
      ) : (
        <>
          <p className="mb-2 text-xs text-ink-dim">
            Pending cash (T+2):{" "}
            <span className="font-mono text-ink">{formatVnd(data?.pending_cash ?? 0)}</span>
          </p>
          {alerts.length === 0 ? (
            <EmptyState>No pending settlements.</EmptyState>
          ) : (
            <table className="w-full text-xs">
              <thead className="text-ink-dim">
                <tr className="text-left">
                  <th className="py-1">Date</th>
                  <th className="py-1">Symbol</th>
                  <th className="py-1">Settling</th>
                  <th className="py-1 text-right">Amount / Qty</th>
                  <th className="py-1 text-right">In</th>
                </tr>
              </thead>
              <tbody className="font-mono text-ink-muted">
                {alerts.map((a, i) => (
                  <tr key={`${a.settlement_date}-${a.symbol}-${i}`} className="border-t border-border">
                    <td className="py-1">{a.settlement_date}</td>
                    <td className="py-1 text-ink">{a.symbol}</td>
                    <td className="py-1">{a.kind === "CASH_IN" ? "Cash" : "Shares"}</td>
                    <td className="py-1 text-right">
                      {a.kind === "CASH_IN" && a.amount != null
                        ? formatVnd(a.amount, { compact: true })
                        : `${a.quantity}`}
                    </td>
                    <td className="py-1 text-right">{a.days_until}d</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </>
      )}
    </Card>
  );
}
