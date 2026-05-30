import type { ReactNode } from "react";

type Tone = "neutral" | "up" | "down" | "warning" | "info" | "mock";

const TONE_CLASSES: Record<Tone, string> = {
  neutral: "bg-bg-subtle text-ink-muted",
  up: "bg-accent-up/15 text-accent-up",
  down: "bg-accent-down/15 text-accent-down",
  warning: "bg-amber-500/15 text-amber-300",
  info: "bg-accent/15 text-accent",
  mock: "bg-purple-500/15 text-purple-300",
};

export function Badge({
  children,
  tone = "neutral",
  title,
}: {
  children: ReactNode;
  tone?: Tone;
  title?: string;
}) {
  return (
    <span
      className={`inline-flex items-center rounded px-1.5 py-0.5 text-[10px] font-medium ${TONE_CLASSES[tone]}`}
      title={title}
    >
      {children}
    </span>
  );
}
