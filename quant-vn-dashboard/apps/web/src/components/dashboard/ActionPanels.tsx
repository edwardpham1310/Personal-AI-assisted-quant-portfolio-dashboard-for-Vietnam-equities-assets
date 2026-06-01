"use client";

import { Card } from "@/components/ui/Card";
import { Badge } from "@/components/ui/Badge";
import { EmptyState } from "@/components/ui/AsyncStates";
import { useRecommendationCandidates } from "@/hooks/useRecommendationCandidates";
import {
  useDataQualityStatus,
  useRiskAlerts,
  useSettlementAlerts,
} from "@/hooks/useDataQualityStatus";
import type { Candidate } from "@/lib/mock/portfolio";

function CandidateList({ rows, action }: { rows: Candidate[]; action: "BUY" | "SELL" }) {
  if (rows.length === 0) return <EmptyState>No candidates today.</EmptyState>;
  return (
    <ul className="space-y-2">
      {rows.map((c) => (
        <li key={c.symbol} className="flex items-start gap-3">
          <Badge tone={action === "BUY" ? "up" : "down"}>{action}</Badge>
          <div className="flex-1">
            <div className="flex items-baseline justify-between">
              <span className="font-mono text-ink">{c.symbol}</span>
              <span className="font-mono text-xs text-ink-dim">{(c.score * 100).toFixed(0)}</span>
            </div>
            <p className="text-xs text-ink-muted">{c.reason}</p>
          </div>
        </li>
      ))}
    </ul>
  );
}

export function ActionPanels() {
  const candidates = useRecommendationCandidates();
  const dq = useDataQualityStatus();
  const risk = useRiskAlerts();
  const settle = useSettlementAlerts();

  return (
    <div className="grid grid-cols-1 gap-4 lg:grid-cols-2 xl:grid-cols-3">
      <Card
        title={
          <>
            Top Buy Candidates
            {candidates.isMock ? (
              <span className="ml-2">
                <Badge tone="mock">Mock</Badge>
              </span>
            ) : null}
          </>
        }
        hint="Rule engine — research signal only, not advice"
      >
        <CandidateList rows={candidates.data.buy} action="BUY" />
      </Card>

      <Card
        title={
          <>
            Top Sell / Reduce Candidates
            {candidates.isMock ? (
              <span className="ml-2">
                <Badge tone="mock">Mock</Badge>
              </span>
            ) : null}
          </>
        }
      >
        <CandidateList rows={candidates.data.sell} action="SELL" />
      </Card>

      <Card
        title={
          <>
            Risk Alerts
            {risk.isMock ? (
              <span className="ml-2">
                <Badge tone="mock">Mock</Badge>
              </span>
            ) : null}
          </>
        }
      >
        {risk.data.length === 0 ? (
          <EmptyState>No active risk alerts.</EmptyState>
        ) : (
          <ul className="space-y-2 text-xs">
            {risk.data.map((a, i) => (
              <li key={i} className="flex items-start gap-2">
                <Badge
                  tone={
                    a.severity === "error" ? "down" : a.severity === "warning" ? "warning" : "info"
                  }
                >
                  {a.severity}
                </Badge>
                <span className="text-ink-muted">{a.message}</span>
              </li>
            ))}
          </ul>
        )}
      </Card>

      <Card
        title={
          <>
            Settlement Alerts
            {settle.isMock ? (
              <span className="ml-2">
                <Badge tone="mock">Mock</Badge>
              </span>
            ) : null}
          </>
        }
        hint="Pending T+2 cash and share settlements"
      >
        {settle.data.length === 0 ? (
          <EmptyState>No upcoming settlements.</EmptyState>
        ) : (
          <ul className="space-y-2 text-xs text-ink-muted">
            {settle.data.map((s, i) => (
              <li key={i}>
                <span className="font-mono text-ink">{s.ts}</span> · {s.message}
              </li>
            ))}
          </ul>
        )}
      </Card>

      <Card
        title={
          <>
            Data Quality
            {dq.isMock ? (
              <span className="ml-2">
                <Badge tone="mock">Mock</Badge>
              </span>
            ) : null}
          </>
        }
        hint={dq.data.note}
      >
        <div className="flex items-baseline gap-3">
          <Badge
            tone={dq.data.status === "OK" ? "up" : dq.data.status === "WARN" ? "warning" : "down"}
          >
            {dq.data.status}
          </Badge>
          <div className="text-xs text-ink-muted">
            ingest lag {dq.data.ingest_lag_minutes}m · {dq.data.issues_24h} issues / 24h
          </div>
        </div>
      </Card>
    </div>
  );
}
