import { Card } from "@/components/ui/Card";
import { StatusPill } from "./StatusPill";
import type { SupabaseHealth } from "@/hooks/useSystemStatus";

export function SupabaseCard({ supabase }: { supabase: SupabaseHealth }) {
  const level = supabase.configured ? "ok" : "warn";
  return (
    <Card
      title={
        <span className="flex items-center gap-2">
          <span>Supabase</span>
          <StatusPill level={level} />
        </span>
      }
      hint="Auth + persistent storage"
    >
      <dl className="grid grid-cols-2 gap-y-1 text-xs">
        <dt className="text-ink-dim">Configured</dt>
        <dd className="text-ink">{supabase.configured ? "yes" : "no"}</dd>
        <dt className="text-ink-dim">URL host</dt>
        <dd className="font-mono text-ink">{supabase.url_host ?? "—"}</dd>
      </dl>
      <p className="mt-2 text-[11px] text-ink-dim">
        Full URL is redacted on the API side and never reaches this card.
      </p>
    </Card>
  );
}
