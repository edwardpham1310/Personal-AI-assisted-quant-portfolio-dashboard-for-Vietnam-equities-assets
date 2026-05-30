import { Card } from "@/components/ui/Card";
import { Badge } from "@/components/ui/Badge";

const FRIENDLY_NAMES: Record<string, string> = {
  supabase_url: "Supabase URL",
  supabase_jwt_secret: "Supabase JWT secret",
  supabase_service_role_key: "Supabase service-role key",
  database_url: "Database URL",
  ssi_consumer_id: "SSI consumer ID",
  ssi_consumer_secret: "SSI consumer secret",
};

export function EnvironmentChecklist({
  missingSecrets,
}: {
  missingSecrets: string[];
}) {
  const allConfigured = missingSecrets.length === 0;
  return (
    <Card
      title={
        <span className="flex items-center gap-2">
          <span>Environment configuration</span>
          {allConfigured ? (
            <Badge tone="up">OK</Badge>
          ) : (
            <Badge tone="warning">{missingSecrets.length} missing</Badge>
          )}
        </span>
      }
      hint="Secrets required by the API to talk to upstream services"
    >
      {allConfigured ? (
        <p className="text-ink-dim text-xs">
          All required secrets are present. The API will boot without
          placeholders.
        </p>
      ) : (
        <ul className="space-y-1.5 text-xs">
          {missingSecrets.map((s) => (
            <li
              key={s}
              className="flex items-center justify-between border-b border-border/40 pb-1"
            >
              <span className="text-ink">
                {FRIENDLY_NAMES[s] ?? s}
                <code className="ml-2 font-mono text-ink-dim">{s.toUpperCase()}</code>
              </span>
              <Badge tone="warning">missing</Badge>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}
