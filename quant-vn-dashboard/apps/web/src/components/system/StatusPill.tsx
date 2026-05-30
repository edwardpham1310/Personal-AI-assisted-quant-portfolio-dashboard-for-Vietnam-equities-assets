import { Badge } from "@/components/ui/Badge";

export type StatusLevel = "ok" | "warn" | "error" | "unknown";

const TONE_BY_LEVEL: Record<StatusLevel, Parameters<typeof Badge>[0]["tone"]> = {
  ok: "up",
  warn: "warning",
  error: "down",
  unknown: "neutral",
};

const LABEL_BY_LEVEL: Record<StatusLevel, string> = {
  ok: "OK",
  warn: "WARN",
  error: "ERROR",
  unknown: "UNKNOWN",
};

export function StatusPill({
  level,
  label,
  title,
}: {
  level: StatusLevel;
  label?: string;
  title?: string;
}) {
  return (
    <Badge tone={TONE_BY_LEVEL[level]} title={title}>
      {label ?? LABEL_BY_LEVEL[level]}
    </Badge>
  );
}
